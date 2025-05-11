import http.client
import json
import random
import os
import time
import logging
from datetime import datetime, timedelta
import requests
import schedule
import pytz

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('prediction_bot')

# Classe principale du bot
class FootballPredictionBot:
    def __init__(self):
        """Initialisation du bot avec les configurations nécessaires."""
        # Récupération des variables d'environnement (à configurer sur Render)
        self.rapidapi_key = os.environ.get('RAPIDAPI_KEY')
        self.rapidapi_host = os.environ.get('RAPIDAPI_HOST', "1xbet-api.p.rapidapi.com")
        self.telegram_bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        self.telegram_channel_id = os.environ.get('TELEGRAM_CHANNEL_ID')
        
        # Vérification des variables d'environnement requises
        self._check_env_variables()
        
        # En-têtes pour l'API RapidAPI
        self.headers = {
            'x-rapidapi-key': self.rapidapi_key,
            'x-rapidapi-host': self.rapidapi_host
        }
        
        # Variables pour stocker les matchs et prédictions
        self.selected_matches = []
        self.predictions = {}
        self.coupon_total_odds = 0
        
        # Fuseau horaire pour l'Afrique centrale
        self.timezone = pytz.timezone('Africa/Brazzaville')
    
    def _check_env_variables(self):
        """Vérifie que toutes les variables d'environnement requises sont définies."""
        missing_vars = []
        
        if not self.rapidapi_key:
            missing_vars.append("RAPIDAPI_KEY")
        
        if not self.telegram_bot_token:
            missing_vars.append("TELEGRAM_BOT_TOKEN")
        
        if not self.telegram_channel_id:
            missing_vars.append("TELEGRAM_CHANNEL_ID")
        
        if missing_vars:
            error_msg = f"Variables d'environnement manquantes: {', '.join(missing_vars)}"
            logger.error(error_msg)
            raise EnvironmentError(error_msg)
    
    def schedule_daily_job(self):
        """Programme l'exécution quotidienne à 8h00 (heure d'Afrique centrale)."""
        # Exécuter immédiatement au démarrage
        self.run_prediction_job()
        
        # Planifier l'exécution quotidienne à 8h00
        schedule.every().day.at("08:00").do(self.run_prediction_job)
        
        logger.info("Bot programmé pour s'exécuter tous les jours à 08:00 (heure d'Afrique centrale)")
        
        # Maintenir le script en fonctionnement
        while True:
            schedule.run_pending()
            time.sleep(60)
    
    def run_prediction_job(self):
        """Fonction principale d'exécution du job de prédiction."""
        logger.info("=== DÉMARRAGE DU JOB DE PRÉDICTIONS FOOTBALL ===")
        
        now = datetime.now(self.timezone)
        logger.info(f"Date/heure actuelle: {now.strftime('%d/%m/%Y %H:%M:%S')}")
        
        # Réinitialiser les variables
        self.selected_matches = []
        self.predictions = {}
        self.coupon_total_odds = 1.0
        
        # Sélectionner les matchs du jour
        self.select_todays_matches()
        
        # Si des matchs ont été trouvés
        if self.selected_matches:
            # Générer des prédictions
            self.generate_predictions()
            
            # Envoyer le coupon sur Telegram
            self.send_predictions_to_telegram()
        else:
            logger.error("Aucun match trouvé pour aujourd'hui. Arrêt du job.")
    
    def make_api_request(self, endpoint):
        """Effectue une requête API avec gestion des erreurs et des tentatives."""
        max_retries = 3
        retry_delay = 2  # secondes
        
        for attempt in range(max_retries):
            try:
                conn = http.client.HTTPSConnection(self.rapidapi_host)
                conn.request("GET", endpoint, headers=self.headers)
                response = conn.getresponse()
                data = response.read()
                
                if response.status == 200:
                    return json.loads(data.decode("utf-8"))
                else:
                    logger.warning(f"Erreur API (tentative {attempt+1}/{max_retries}): Code {response.status}")
                    logger.warning(f"Réponse: {data.decode('utf-8')}")
                    if attempt < max_retries - 1:
                        logger.info(f"Nouvelle tentative dans {retry_delay} secondes...")
                        time.sleep(retry_delay)
            except Exception as e:
                logger.error(f"Erreur de connexion (tentative {attempt+1}/{max_retries}): {str(e)}")
                if attempt < max_retries - 1:
                    logger.info(f"Nouvelle tentative dans {retry_delay} secondes...")
                    time.sleep(retry_delay)
        
        logger.error(f"Échec de la requête après {max_retries} tentatives: {endpoint}")
        return None
    
    def get_todays_matches(self):
        """Récupère les matchs du jour."""
        # Définir la plage horaire pour les matchs (aujourd'hui)
        now = datetime.now(self.timezone)
        today_start = datetime(now.year, now.month, now.day, 0, 0, 0).replace(tzinfo=self.timezone)
        today_end = datetime(now.year, now.month, now.day, 23, 59, 59).replace(tzinfo=self.timezone)
        
        start_timestamp = int(today_start.timestamp())
        end_timestamp = int(today_end.timestamp())
        
        logger.info(f"Recherche de matchs pour aujourd'hui ({now.strftime('%d/%m/%Y')})...")
        
        # Liste pour stocker tous les matchs trouvés
        all_matches = []
        
        # Championnats populaires à consulter
        leagues_to_check = [
            {"id": 148, "name": "Ligue 1"},        # France
            {"id": 110, "name": "Serie A"},        # Italie
            {"id": 127, "name": "La Liga"},        # Espagne
            {"id": 136, "name": "Bundesliga"},     # Allemagne
            {"id": 118, "name": "Premier League"}, # Angleterre
            {"id": 251, "name": "UEFA Champions League"},
            {"id": 252, "name": "UEFA Europa League"},
            {"id": 253, "name": "UEFA Conference League"},
            {"id": 246, "name": "Japanese J League"},
            {"id": 247, "name": "Korean K League"},
            {"id": 248, "name": "Chinese Super League"},
            {"id": 88, "name": "MLS"},             # USA
            {"id": 98, "name": "Brazilian Serie A"},
            {"id": 100, "name": "Argentine Primera División"}
        ]
        
        for league in leagues_to_check:
            league_id = league["id"]
            league_name = league["name"]
            
            logger.info(f"Recherche dans {league_name} (ID: {league_id})...")
            
            # Récupérer les matchs pour cette ligue
            endpoint = f"/matches?sport_id=1&league_id={league_id}&mode=line&lng=en"
            response = self.make_api_request(endpoint)
            
            if not response or response.get("status") != "success":
                logger.warning(f"Aucun match trouvé dans {league_name}")
                continue
            
            matches = response.get("data", [])
            
            # Filtrer les matchs qui se déroulent aujourd'hui
            league_matches_count = 0
            for match in matches:
                match_timestamp = match.get("start_timestamp", 0)
                
                if start_timestamp <= match_timestamp <= end_timestamp:
                    # Ajouter le nom de la ligue aux informations du match
                    match["league_name"] = league_name
                    match["league_id"] = league_id
                    all_matches.append(match)
                    league_matches_count += 1
            
            if league_matches_count > 0:
                logger.info(f"Trouvé {league_matches_count} match(s) pour aujourd'hui dans {league_name}")
            
            # Attendre un court moment entre les requêtes pour éviter les limites d'API
            time.sleep(0.5)
        
        logger.info(f"Total des matchs trouvés pour aujourd'hui: {len(all_matches)}")
        return all_matches
    
    def select_todays_matches(self):
        """Sélectionne jusqu'à 5 matchs parmi les matchs du jour."""
        all_matches = self.get_todays_matches()
        
        if not all_matches:
            logger.warning("Aucun match trouvé pour aujourd'hui.")
            return
        
        # Limiter à 5 matchs maximum
        max_matches = min(5, len(all_matches))
        
        if len(all_matches) <= max_matches:
            self.selected_matches = all_matches
        else:
            self.selected_matches = random.sample(all_matches, max_matches)
        
        logger.info(f"=== SÉLECTION DE {len(self.selected_matches)} MATCH(S) POUR LES PRÉDICTIONS ===")
        
        # Afficher les matchs sélectionnés
        for i, match in enumerate(self.selected_matches):
            start_timestamp = match.get("start_timestamp", 0)
            start_time = datetime.fromtimestamp(start_timestamp, self.timezone)
            
            logger.info(f"Match {i+1}: {match.get('home_team')} vs {match.get('away_team')} - {match.get('league_name')}")
            logger.info(f"  ID: {match.get('id')}")
            logger.info(f"  Heure de début: {start_time.strftime('%d/%m/%Y %H:%M')}")
    
    def get_match_odds(self, match_id):
        """Récupère les cotes pour un match spécifique."""
        endpoint = f"/matches/{match_id}/markets?mode=line&lng=en"
        response = self.make_api_request(endpoint)
        
        if not response or response.get("status") != "success":
            logger.warning(f"Impossible de récupérer les cotes pour le match ID: {match_id}")
            return None
        
        return response.get("data", {})
    
    def is_handicap_king_applicable(self, markets):
        """Vérifie si la stratégie 'Le Handicap du Roi' est applicable."""
        if "1" not in markets or "16" not in markets:  # 1 = 1X2, 16 = Handicap
            return False, None
        
        # Trouver la cote pour la victoire simple
        victory_odds = None
        for outcome in markets["1"].get("outcomes", []):
            if outcome.get("name") == "1":  # Victoire domicile
                victory_odds = outcome.get("odds")
                break
        
        if not victory_odds or victory_odds > 1.90:
            return False, None
        
        # Trouver la cote pour la victoire avec handicap -1
        handicap_odds = None
        for outcome in markets["16"].get("outcomes", []):
            if "1" in outcome.get("name", "") and "-1" in outcome.get("name", ""):
                handicap_odds = outcome.get("odds")
                break
        
        if not handicap_odds:
            return False, None
        
        # Calculer l'écart entre les deux cotes
        odds_difference = handicap_odds - victory_odds
        
        # Vérifier si l'écart est dans la plage souhaitée (0.35-0.60)
        if 0.35 <= odds_difference <= 0.60:
            return True, {"type": "Handicap -1", "odds": handicap_odds}
        
        return False, None
    
    def is_first_half_goal_applicable(self, markets):
        """Vérifie si la stratégie 'Le Premier Feu Sacré' est applicable."""
        # Rechercher la cote pour +1.5 buts en première mi-temps
        first_half_over = None
        
        # Parcourir différents marchés possibles pour trouver la cote
        for market_id in markets:
            market = markets[market_id]
            if "first half" in market.get("name", "").lower() and "total" in market.get("name", "").lower():
                for outcome in market.get("outcomes", []):
                    if "over 1.5" in outcome.get("name", "").lower():
                        first_half_over = outcome.get("odds")
                        break
        
        if not first_half_over or first_half_over > 1.80:
            return False, None
        
        # Trouver la cote pour +0.5 but en première mi-temps (cote généralement basse)
        first_half_one_goal = None
        for market_id in markets:
            market = markets[market_id]
            if "first half" in market.get("name", "").lower() and "total" in market.get("name", "").lower():
                for outcome in market.get("outcomes", []):
                    if "over 0.5" in outcome.get("name", "").lower():
                        first_half_one_goal = outcome.get("odds")
                        break
        
        if not first_half_one_goal:
            return False, None
        
        return True, {"type": "+0.5 but 1ère mi-temps", "odds": first_half_one_goal}
    
    def is_trapped_draw_applicable(self, markets):
        """Vérifie si la stratégie 'Le Nul Piégé' est applicable."""
        if "1" not in markets:  # 1 = 1X2
            return False, None
        
        # Récupérer les cotes 1X2
        home_odds = away_odds = draw_odds = None
        for outcome in markets["1"].get("outcomes", []):
            if outcome.get("name") == "1":  # Victoire domicile
                home_odds = outcome.get("odds")
            elif outcome.get("name") == "2":  # Victoire extérieur
                away_odds = outcome.get("odds")
            elif outcome.get("name") == "X":  # Match nul
                draw_odds = outcome.get("odds")
        
        if not all([home_odds, away_odds, draw_odds]):
            return False, None
        
        # Vérifier si la cote du match nul est <= 3.50
        if draw_odds <= 3.50:
            # Déterminer quelle équipe est favorite
            if home_odds < away_odds:
                return True, {"type": "1X", "odds": min(1.70, home_odds * 0.70)}  # Double chance domicile ou nul
            else:
                return True, {"type": "X2", "odds": min(1.70, away_odds * 0.70)}  # Double chance extérieur ou nul
        
        return False, None
    
    def is_both_teams_to_score_applicable(self, markets):
        """Vérifie si la stratégie 'Le Pacte des Deux Buteurs' est applicable."""
        home_total_over = away_total_over = match_total_over = None
        
        # Rechercher les cotes pour les totaux
        for market_id in markets:
            market = markets[market_id]
            # Recherche du total pour l'équipe à domicile
            if "team 1" in market.get("name", "").lower() and "total" in market.get("name", "").lower():
                for outcome in market.get("outcomes", []):
                    if "over 1.5" in outcome.get("name", "").lower():
                        home_total_over = outcome.get("odds")
            
            # Recherche du total pour l'équipe à l'extérieur
            elif "team 2" in market.get("name", "").lower() and "total" in market.get("name", "").lower():
                for outcome in market.get("outcomes", []):
                    if "over 1.5" in outcome.get("name", "").lower():
                        away_total_over = outcome.get("odds")
            
            # Recherche du total pour le match
            elif "total" in market.get("name", "").lower() and not "team" in market.get("name", "").lower():
                for outcome in market.get("outcomes", []):
                    if "over 2.5" in outcome.get("name", "").lower():
                        match_total_over = outcome.get("odds")
        
        # Rechercher la cote pour "Les deux équipes marquent"
        btts_odds = None
        for market_id in markets:
            market = markets[market_id]
            if "both teams to score" in market.get("name", "").lower():
                for outcome in market.get("outcomes", []):
                    if outcome.get("name", "").lower() in ["yes", "oui"]:
                        btts_odds = outcome.get("odds")
        
        # Vérifier les conditions pour appliquer la stratégie
        if (home_total_over and home_total_over <= 2.00 and
            away_total_over and away_total_over <= 2.20 and
            match_total_over and match_total_over <= 1.70 and
            btts_odds):
            return True, {"type": "Les 2 équipes marquent", "odds": btts_odds}
        
        return False, None
    
    def is_under_goals_applicable(self, markets):
        """Vérifie si la stratégie pour parier sur moins de buts est applicable."""
        # Rechercher les cotes pour les scores exacts
        if "18" not in markets:  # 18 = Score exact
            return False, None
        
        scores = []
        for outcome in markets["18"].get("outcomes", []):
            scores.append({"name": outcome.get("name"), "odds": outcome.get("odds")})
        
        # Trier les scores par cote (du plus bas au plus haut)
        scores.sort(key=lambda x: x["odds"])
        
        # Vérifier si les 3 cotes les plus basses sont toutes < 7.00
        if len(scores) >= 3 and all(score["odds"] < 7.00 for score in scores[:3]):
            # Rechercher la cote pour "Moins de 3,5 buts"
            under_odds = None
            for market_id in markets:
                market = markets[market_id]
                if "total" in market.get("name", "").lower():
                    for outcome in market.get("outcomes", []):
                        if "under 3.5" in outcome.get("name", "").lower():
                            under_odds = outcome.get("odds")
            
            if under_odds:
                return True, {"type": "-3.5 buts", "odds": under_odds}
        
        return False, None
    
    def determine_best_prediction(self, match_id, home_team, away_team, markets):
        """Détermine la meilleure prédiction pour un match en fonction des stratégies."""
        predictions = []
        
        # Vérifier chaque stratégie
        handicap_king, handicap_pred = self.is_handicap_king_applicable(markets)
        if handicap_king:
            predictions.append({
                "strategy": "Le Handicap du Roi",
                "prediction": f"{home_team} gagne",
                "type": handicap_pred["type"],
                "odds": handicap_pred["odds"],
                "confidence": 0.85
            })
        
        first_half_goal, first_half_pred = self.is_first_half_goal_applicable(markets)
        if first_half_goal:
            predictions.append({
                "strategy": "Le Premier Feu Sacré",
                "prediction": first_half_pred["type"],
                "type": first_half_pred["type"],
                "odds": first_half_pred["odds"],
                "confidence": 0.80
            })
        
        trapped_draw, draw_pred = self.is_trapped_draw_applicable(markets)
        if trapped_draw:
            predictions.append({
                "strategy": "Le Nul Piégé",
                "prediction": draw_pred["type"],
                "type": draw_pred["type"],
                "odds": draw_pred["odds"],
                "confidence": 0.75
            })
        
        btts, btts_pred = self.is_both_teams_to_score_applicable(markets)
        if btts:
            predictions.append({
                "strategy": "Le Pacte des Deux Buteurs",
                "prediction": btts_pred["type"],
                "type": btts_pred["type"],
                "odds": btts_pred["odds"],
                "confidence": 0.78
            })
        
        under_goals, under_pred = self.is_under_goals_applicable(markets)
        if under_goals:
            predictions.append({
                "strategy": "Le Poids des Petites Cotes",
                "prediction": under_pred["type"],
                "type": under_pred["type"],
                "odds": under_pred["odds"],
                "confidence": 0.82
            })
        
        # Si aucune prédiction n'est applicable, retourner None
        if not predictions:
            return None
        
        # Trier les prédictions par niveau de confiance (du plus élevé au plus bas)
        predictions.sort(key=lambda x: x["confidence"], reverse=True)
        
        # Retourner la prédiction avec le niveau de confiance le plus élevé
        best_prediction = predictions[0]
        
        return {
            "match_id": match_id,
            "home_team": home_team,
            "away_team": away_team,
            "prediction": best_prediction["prediction"],
            "type": best_prediction["type"],
            "odds": best_prediction["odds"],
            "strategy": best_prediction["strategy"],
            "confidence": best_prediction["confidence"]
        }
    
    def generate_predictions(self):
        """Génère les meilleures prédictions pour les matchs sélectionnés."""
        logger.info("=== GÉNÉRATION DES PRÉDICTIONS ===")
        
        valid_predictions = 0
        
        for match in self.selected_matches:
            match_id = match.get("id")
            home_team = match.get("home_team")
            away_team = match.get("away_team")
            league_name = match.get("league_name", "Ligue inconnue")
            
            logger.info(f"Analyse du match {home_team} vs {away_team} (ID: {match_id})...")
            
            # Récupérer les cotes pour ce match
            markets = self.get_match_odds(match_id)
            
            if not markets:
                logger.warning(f"Pas de cotes disponibles pour {home_team} vs {away_team}, match ignoré")
                continue
            
            # Déterminer la meilleure prédiction pour ce match
            best_prediction = self.determine_best_prediction(match_id, home_team, away_team, markets)
            
            if best_prediction:
                # Ajouter les informations supplémentaires
                best_prediction["league_name"] = league_name
                best_prediction["start_timestamp"] = match.get("start_timestamp", 0)
                
                # Stocker la prédiction
                self.predictions[match_id] = best_prediction
                valid_predictions += 1
                
                logger.info(f"  Prédiction pour {home_team} vs {away_team}: {best_prediction['prediction']} (Cote: {best_prediction['odds']})")
                logger.info(f"  Stratégie utilisée: {best_prediction['strategy']}")
            else:
                logger.warning(f"Aucune prédiction fiable trouvée pour {home_team} vs {away_team}")
        
        # Calculer la cote totale du coupon
        if self.predictions:
            self.coupon_total_odds = 1.0
            for match_id, pred in self.predictions.items():
                self.coupon_total_odds *= pred["odds"]
            self.coupon_total_odds = round(self.coupon_total_odds, 2)
        
        logger.info(f"Prédictions générées pour {valid_predictions} match(s) avec une cote totale de {self.coupon_total_odds}")
    
    def format_prediction_message(self):
        """Formate le message de prédiction pour Telegram."""
        now = datetime.now(self.timezone)
        date_str = now.strftime("%d/%m/%Y")
        
        message = f"🔮 *COUPON DE PRÉDICTIONS DU JOUR* 🔮\n"
        message += f"📅 *{date_str}*\n\n"
        
        # Si aucune prédiction n'a été générée
        if not self.predictions:
            message += "_Aucune prédiction fiable n'a pu être générée pour aujourd'hui. Revenez demain!_"
            return message
        
        # Ajouter chaque prédiction au message
        for i, (match_id, pred) in enumerate(self.predictions.items()):
            # Séparateur
            if i > 0:
                message += "----------------------------\n\n"
            
            # Calculer l'heure du match au format local
            start_time = datetime.fromtimestamp(pred["start_timestamp"], self.timezone).strftime("%H:%M")
            
            message += f"🏆 *{pred['league_name'].upper()}*\n"
            message += f"⚽ *{pred['home_team']} vs {pred['away_team']}* | {start_time}\n"
            message += f"🎯 *Prédiction:* {pred['prediction']}\n"
            message += f"💰 *Cote:* {pred['odds']}\n\n"
        
        # Ajouter la cote totale
        message += f"----------------------------\n\n"
        message += f"📊 *COTE TOTALE:* {self.coupon_total_odds}\n\n"
        
        # Conseil de bankroll
        message += f"💡 _Conseil: Investissez 5% de votre capital sur ce coupon pour une gestion optimale de votre bankroll._"
        
        return message
    
    def send_to_telegram(self, message):
        """Envoie un message sur le canal Telegram."""
        url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
        
        try:
            data = {
                "chat_id": self.telegram_channel_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            
            response = requests.post(url, data=data)
            
            if response.status_code == 200:
                logger.info("Message envoyé avec succès sur Telegram")
                return True
            else:
                logger.error(f"Erreur lors de l'envoi du message sur Telegram: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Exception lors de l'envoi du message sur Telegram: {str(e)}")
            return False
    
    def send_predictions_to_telegram(self):
        """Envoie les prédictions sur le canal Telegram."""
        message = self.format_prediction_message()
        
        logger.info("Envoi des prédictions sur Telegram...")
        success = self.send_to_telegram(message)
        
        if success:
            logger.info("Prédictions envoyées avec succès")
        else:
            logger.error("Échec de l'envoi des prédictions")

# Point d'entrée principal
if __name__ == "__main__":
    try:
        bot = FootballPredictionBot()
        bot.schedule_daily_job()
    except Exception as e:
        logger.critical(f"Erreur fatale: {str(e)}")
        # Afficher la trace complète de l'erreur pour faciliter le débogage
        import traceback
        logger.critical(traceback.format_exc())
