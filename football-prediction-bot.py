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
        """Programme l'exécution quotidienne à 7h00 (heure d'Afrique centrale)."""
        # Exécuter immédiatement au démarrage
        self.run_prediction_job()
        
        # Planifier l'exécution quotidienne à 7h00
        schedule.every().day.at("07:00").do(self.run_prediction_job)
        
        logger.info("Bot programmé pour s'exécuter tous les jours à 07:00 (heure d'Afrique centrale)")
        
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

    def find_under_35_goals(self, markets):
        """Recherche la prédiction Under 3.5 buts."""
        for market_id, market in markets.items():
            market_name = market.get("name", "").lower()
            
            if "total" in market_name and not "team" in market_name:
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    if "under" in name and "3.5" in name and odds:
                        # On vérifie si la cote est assez intéressante (< 1.40)
                        if odds < 1.40:
                            return {
                                "type": "-3.5 buts",
                                "odds": odds,
                                "confidence": 0.90
                            }
        
        return None

    def find_over_15_goals(self, markets):
        """Recherche la prédiction Over 1.5 buts."""
        for market_id, market in markets.items():
            market_name = market.get("name", "").lower()
            
            if "total" in market_name and not "team" in market_name:
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    if "over" in name and "1.5" in name and odds:
                        # On vérifie si la cote est assez intéressante (< 1.40)
                        if odds < 1.40:
                            return {
                                "type": "+1.5 buts",
                                "odds": odds,
                                "confidence": 0.88
                            }
        
        return None

    def find_double_chance(self, markets):
        """Recherche la prédiction de Double Chance (1X, X2, 12)."""
        for market_id, market in markets.items():
            market_name = market.get("name", "").lower()
            
            if "double chance" in market_name:
                best_dc = None
                best_odds = 0
                best_conf = 0
                
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "")
                    odds = outcome.get("odds")
                    
                    if not odds:
                        continue
                    
                    if name == "1X" and odds < 1.50:
                        # 1X: Victoire domicile ou match nul
                        confidence = 0.85
                        dc_type = "1X"
                    elif name == "X2" and odds < 1.50:
                        # X2: Match nul ou victoire extérieur
                        confidence = 0.85
                        dc_type = "X2"
                    elif name == "12" and odds < 1.40:
                        # 12: Victoire domicile ou victoire extérieur
                        confidence = 0.80
                        dc_type = "12"
                    else:
                        continue
                    
                    # Si cette option est meilleure que les précédentes
                    if confidence > best_conf:
                        best_dc = dc_type
                        best_odds = odds
                        best_conf = confidence
                
                if best_dc:
                    return {
                        "type": best_dc,
                        "odds": best_odds,
                        "confidence": best_conf
                    }
        
        return None

    def generate_match_prediction(self, match_id, markets):
        """Génère une prédiction pour un match spécifique."""
        # Liste des fonctions de prédiction dans l'ordre de priorité
        prediction_functions = [
            self.find_under_35_goals,
            self.find_over_15_goals,
            self.find_double_chance
        ]
        
        # Essayer chaque fonction dans l'ordre
        for func in prediction_functions:
            prediction = func(markets)
            if prediction:
                return prediction
        
        # Si aucune prédiction n'a été trouvée, renvoyer None
        return None
    
    def generate_predictions(self):
        """Génère les meilleures prédictions pour les matchs sélectionnés."""
        logger.info("=== GÉNÉRATION DES PRÉDICTIONS ===")
        
        # Liste des types de prédictions déjà utilisés
        used_prediction_types = []
        
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
            
            # Générer une prédiction pour ce match
            prediction = self.generate_match_prediction(match_id, markets)
            
            # Si une prédiction a été trouvée
            if prediction:
                # Vérifier si le type de prédiction a déjà été utilisé
                if prediction["type"] in used_prediction_types and len(self.selected_matches) > 2:
                    # Chercher une prédiction alternative
                    for func in [self.find_under_35_goals, self.find_over_15_goals, self.find_double_chance]:
                        alt_prediction = func(markets)
                        if alt_prediction and alt_prediction["type"] not in used_prediction_types:
                            prediction = alt_prediction
                            break
                
                # Ajouter les informations du match
                prediction["match_id"] = match_id
                prediction["home_team"] = home_team
                prediction["away_team"] = away_team
                prediction["league_name"] = league_name
                prediction["start_timestamp"] = match.get("start_timestamp", 0)
                
                # Stocker la prédiction
                self.predictions[match_id] = prediction
                used_prediction_types.append(prediction["type"])
                
                logger.info(f"  Prédiction pour {home_team} vs {away_team}: {prediction['type']} (Cote: {prediction['odds']})")
            else:
                logger.warning(f"Aucune prédiction fiable trouvée pour {home_team} vs {away_team}")
        
        # Calculer la cote totale du coupon
        if self.predictions:
            self.coupon_total_odds = 1.0
            for match_id, pred in self.predictions.items():
                self.coupon_total_odds *= pred["odds"]
            self.coupon_total_odds = round(self.coupon_total_odds, 2)
        
        logger.info(f"Prédictions générées pour {len(self.predictions)} match(s) avec une cote totale de {self.coupon_total_odds}")
    
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
            message += f"🎯 *Prédiction:* *{pred['type']}*\n"
            message += f"💰 *Cote:* *{pred['odds']}*\n\n"
        
        # Ajouter la cote totale
        message += f"----------------------------\n\n"
        message += f"📊 *COTE TOTALE: {self.coupon_total_odds}*\n\n"
        
        # Conseil de bankroll et jeu responsable
        message += f"_💡 Misez seulement 5% de votre capital sur ce coupon._\n"
        message += f"_🔞 Pariez de façon responsable. Jeux interdits aux mineurs._"
        
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
