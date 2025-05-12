import http.client
import json
import random
import os
import time
import logging
from datetime import datetime, timedelta
import requests
import pytz
import schedule

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
        
        # Cote minimale pour les prédictions
        self.min_odds = 1.15
        
        # Cote maximale à accepter pour les prédictions (pour éviter les paris trop risqués)
        self.max_odds = 2.50
        
        # Liste des IDs de ligue connus qui fonctionnent
        self.league_ids = [1, 118, 148, 127, 110, 136, 251, 252, 253, 301, 302, 303, 304]
        
        # Championnats à faible scoring (priorité pour les prédictions "under")
        self.low_scoring_leagues = [
            # Championnats africains
            "ghana", "nigeria", "kenya", "tanzania", "ethiopia", "south africa", 
            "morocco", "algeria", "tunisia", "cameroon", "ivory coast", "senegal",
            # Championnats latino-américains avec faible scoring
            "peru", "bolivia", "venezuela", "ecuador", "colombia",
            # Championnats secondaires européens
            "belarus", "estonia", "latvia", "lithuania", "finland", "iceland"
        ]
        
        # Seuils de cotes pour différents types de paris
        self.odds_thresholds = {
            "under_goals": 1.20,  # Seuil minimal pour under goals
            "over_goals": 1.25,   # Seuil minimal pour over goals
            "btts": 1.40,         # Seuil minimal pour les 2 équipes marquent
            "double_chance": 1.15  # Seuil minimal pour double chance
        }
    
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
        
        # Récupérer tous les matchs disponibles
        all_matches = self.get_todays_matches()
        
        if all_matches:
            # Sélectionner des matchs pour les prédictions
            self.select_matches(all_matches)
            
            # Générer des prédictions
            if self.selected_matches:
                self.generate_predictions()
                
                # Envoyer le coupon sur Telegram
                self.send_predictions_to_telegram()
            else:
                logger.error("Aucun match sélectionné pour les prédictions.")
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
        """Récupère les matchs du jour en utilisant les IDs de ligue connus."""
        # Obtenir l'heure actuelle
        now = datetime.now(self.timezone)
        now_timestamp = int(now.timestamp())
        
        # Définir la plage horaire pour les matchs (aujourd'hui)
        today_start = datetime(now.year, now.month, now.day, 0, 0, 0).replace(tzinfo=self.timezone)
        today_end = datetime(now.year, now.month, now.day, 23, 59, 59).replace(tzinfo=self.timezone)
        
        start_timestamp = int(today_start.timestamp())
        end_timestamp = int(today_end.timestamp())
        
        logger.info(f"Recherche de matchs pour aujourd'hui ({now.strftime('%d/%m/%Y')})...")
        
        # Liste pour stocker tous les matchs trouvés
        all_matches = []
        
        # Parcourir tous les IDs de ligue connus
        for league_id in self.league_ids:
            logger.info(f"Recherche de matchs pour league_id={league_id}...")
            
            # Récupérer les matchs de cette ligue
            endpoint = f"/matches?sport_id=1&league_id={league_id}&mode=line&lng=en"
            response = self.make_api_request(endpoint)
            
            if not response or response.get("status") != "success":
                logger.warning(f"Aucun match trouvé pour league_id={league_id}")
                continue
            
            # Récupérer la liste des matchs
            matches = response.get("data", [])
            
            # Vérifier si matches est une liste
            if not isinstance(matches, list):
                logger.warning(f"Format de données inattendu pour league_id={league_id}")
                continue
            
            # Filtrer les matchs qui se déroulent aujourd'hui et qui ne sont pas encore commencés
            league_matches_count = 0
            for match in matches:
                match_timestamp = match.get("start_timestamp", 0)
                
                # Vérifier si le match se déroule aujourd'hui
                if start_timestamp <= match_timestamp <= end_timestamp:
                    # Vérifier que le match n'a pas encore commencé
                    if match_timestamp > now_timestamp:
                        # Vérifier que toutes les informations nécessaires sont présentes
                        if (match.get("home_team") and 
                            match.get("away_team") and 
                            match.get("league") and 
                            match.get("id")):
                            
                            # Ajouter le match à notre liste
                            all_matches.append(match)
                            league_matches_count += 1
            
            if league_matches_count > 0:
                logger.info(f"Trouvé {league_matches_count} match(s) à venir pour aujourd'hui dans league_id={league_id}")
            
            # Attendre un court moment entre les requêtes pour éviter les limites d'API
            time.sleep(0.5)
        
        logger.info(f"Total des matchs à venir trouvés pour aujourd'hui: {len(all_matches)}")
        return all_matches
    
    def is_low_scoring_league(self, league_name):
        """Détermine si une ligue est considérée comme à faible scoring."""
        if not league_name:
            return False
            
        league_name_lower = league_name.lower()
        return any(league in league_name_lower for league in self.low_scoring_leagues)
    
    def select_matches(self, all_matches):
        """Sélectionne des matchs pour les prédictions en donnant priorité aux ligues à faible scoring."""
        if not all_matches:
            logger.warning("Aucun match disponible pour la sélection.")
            return
        
        # Trier les matchs en deux catégories: championnats à faible scoring et autres
        low_scoring_matches = []
        other_matches = []
        
        for match in all_matches:
            league_name = match.get("league", "")
            if self.is_low_scoring_league(league_name):
                low_scoring_matches.append(match)
            else:
                other_matches.append(match)
        
        logger.info(f"Matchs de championnats à faible scoring disponibles: {len(low_scoring_matches)}")
        logger.info(f"Autres matchs disponibles: {len(other_matches)}")
        
        # Donner la priorité aux matchs de ligues à faible scoring (au moins 60% des sélections)
        max_matches = min(5, len(all_matches))
        low_scoring_quota = max(1, int(max_matches * 0.6))
        
        selected_low_scoring = []
        selected_other = []
        
        # Sélectionner des matchs de ligues à faible scoring
        if low_scoring_matches:
            selected_low_scoring = random.sample(
                low_scoring_matches, 
                min(low_scoring_quota, len(low_scoring_matches))
            )
        
        # Compléter avec d'autres matchs
        remaining_slots = max_matches - len(selected_low_scoring)
        if remaining_slots > 0 and other_matches:
            selected_other = random.sample(
                other_matches, 
                min(remaining_slots, len(other_matches))
            )
        
        # Combiner les sélections
        self.selected_matches = selected_low_scoring + selected_other
        
        logger.info(f"=== SÉLECTION DE {len(self.selected_matches)} MATCH(S) POUR LES PRÉDICTIONS ===")
        logger.info(f"Dont {len(selected_low_scoring)} matchs de ligues à faible scoring et {len(selected_other)} autres matchs")
        
        # Afficher les matchs sélectionnés
        for i, match in enumerate(self.selected_matches):
            start_timestamp = match.get("start_timestamp", 0)
            start_time = datetime.fromtimestamp(start_timestamp, self.timezone)
            home_team = match.get("home_team", "Équipe inconnue")
            away_team = match.get("away_team", "Équipe inconnue")
            league_name = match.get("league", "Ligue inconnue")
            
            logger.info(f"Match {i+1}: {home_team} vs {away_team} - {league_name}")
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

    def find_under_25_goals(self, markets):
        """Recherche la prédiction Under 2.5 buts - idéal pour les matchs de ligues à faible scoring."""
        min_odds = self.odds_thresholds["under_goals"]
        
        for market_id, market in markets.items():
            market_name = market.get("name", "").lower()
            
            if "total" in market_name and not "team" in market_name:
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    if "under" in name and "2.5" in name and odds:
                        if min_odds <= odds <= self.max_odds:
                            return {
                                "type": "-2.5 buts",
                                "odds": odds,
                                "confidence": 0.92
                            }
        
        return None

    def find_under_35_goals(self, markets):
        """Recherche la prédiction Under 3.5 buts - bonne option pour la plupart des matchs."""
        min_odds = self.odds_thresholds["under_goals"]
        
        for market_id, market in markets.items():
            market_name = market.get("name", "").lower()
            
            if "total" in market_name and not "team" in market_name:
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    if "under" in name and "3.5" in name and odds:
                        if min_odds <= odds <= self.max_odds:
                            return {
                                "type": "-3.5 buts",
                                "odds": odds,
                                "confidence": 0.90
                            }
        
        return None

    def find_over_05_goals(self, markets):
        """Recherche la prédiction Over 0.5 buts - option très sûre."""
        min_odds = self.odds_thresholds["over_goals"]
        
        for market_id, market in markets.items():
            market_name = market.get("name", "").lower()
            
            if "total" in market_name and not "team" in market_name:
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    if "over" in name and "0.5" in name and odds:
                        if min_odds <= odds <= self.max_odds:
                            return {
                                "type": "+0.5 buts",
                                "odds": odds,
                                "confidence": 0.95
                            }
        
        return None

    def find_over_15_goals(self, markets):
        """Recherche la prédiction Over 1.5 buts."""
        min_odds = self.odds_thresholds["over_goals"]
        
        for market_id, market in markets.items():
            market_name = market.get("name", "").lower()
            
            if "total" in market_name and not "team" in market_name:
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    if "over" in name and "1.5" in name and odds:
                        if min_odds <= odds <= self.max_odds:
                            return {
                                "type": "+1.5 buts",
                                "odds": odds,
                                "confidence": 0.85
                            }
        
        return None

    def find_both_teams_to_score(self, markets):
        """Recherche la prédiction Les deux équipes marquent - à utiliser avec précaution."""
        min_odds = self.odds_thresholds["btts"]
        
        for market_id, market in markets.items():
            market_name = market.get("name", "").lower()
            
            if "both teams to score" in market_name:
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    if (name in ["yes", "oui"] or "yes" in name) and odds:
                        if min_odds <= odds <= self.max_odds:
                            return {
                                "type": "Les 2 équipes marquent",
                                "odds": odds,
                                "confidence": 0.75
                            }
        
        return None

    def find_double_chance(self, markets):
        """Recherche la prédiction de Double Chance (1X, X2, 12) - bonne option pour équipes favorites."""
        min_odds = self.odds_thresholds["double_chance"]
        
        for market_id, market in markets.items():
            market_name = market.get("name", "").lower()
            
            if "double chance" in market_name:
                best_dc = None
                best_odds = 0
                best_conf = 0
                
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "")
                    odds = outcome.get("odds")
                    
                    if not odds or odds < min_odds or odds > self.max_odds:
                        continue
                    
                    if name == "1X":
                        # 1X: Victoire domicile ou match nul
                        confidence = 0.88
                        dc_type = "1X"
                    elif name == "X2":
                        # X2: Match nul ou victoire extérieur
                        confidence = 0.85
                        dc_type = "X2"
                    elif name == "12":
                        # 12: Victoire domicile ou victoire extérieur
                        confidence = 0.82
                        dc_type = "12"
                    else:
                        continue
                    
                    # Priorité à la meilleure option selon la confiance et la cote
                    if odds > best_odds and confidence >= best_conf:
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
        """Génère une prédiction pour un match spécifique en tenant compte des spécificités régionales."""
        
        # Récupérer les informations du match
        match_info = next((m for m in self.selected_matches if m.get("id") == match_id), None)
        league_name = match_info.get("league", "") if match_info else ""
        
        # Déterminer si c'est un championnat à faible scoring
        is_low_scoring = self.is_low_scoring_league(league_name)
        
        # Priorités différentes selon le type de championnat
        if is_low_scoring:
            prediction_functions = [
                self.find_under_25_goals,     # Priorité aux matchs avec peu de buts
                self.find_under_35_goals,     # Deuxième option pour peu de buts
                self.find_double_chance,      # Double chance bien adaptée
                self.find_over_05_goals,      # Option sûre pour au moins un but
                self.find_both_teams_to_score # Dernière option car moins probable
            ]
            logger.info(f"Utilisation des priorités de ligue à faible scoring pour {league_name}")
        else:
            prediction_functions = [
                self.find_double_chance,      # Priorité au double chance dans autres ligues
                self.find_under_35_goals,     # Ensuite les under goals
                self.find_over_15_goals,      # Plus de buts dans ces ligues
                self.find_both_teams_to_score,# Plus probable dans ces ligues
                self.find_over_05_goals       # Option de secours
            ]
            logger.info(f"Utilisation des priorités standard pour {league_name}")
        
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
        
        # Trier les matchs par priorité (championnats à faible scoring d'abord)
        sorted_matches = sorted(
            self.selected_matches,
            key=lambda m: self.is_low_scoring_league(m.get("league", "")),
            reverse=True
        )
        
        for match in sorted_matches:
            match_id = match.get("id")
            home_team = match.get("home_team", "Équipe domicile")
            away_team = match.get("away_team", "Équipe extérieur")
            league_name = match.get("league", "Ligue inconnue")
            
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
                    # Pour les ligues à faible scoring, les "under goals" sont acceptables même si répétitifs
                    is_under_prediction = "under" in prediction["type"].lower() or "-" in prediction["type"]
                    is_low_scoring_match = self.is_low_scoring_league(league_name)
                    
                    if not (is_low_scoring_match and is_under_prediction):
                        # Chercher une prédiction alternative
                        logger.info(f"Recherche d'une prédiction alternative (type {prediction['type']} déjà utilisé)")
                        
                        # Essayer avec une liste différente de fonctions
                        for func in [
                            self.find_double_chance,  # Priorité pour l'alternative
                            self.find_under_35_goals,
                            self.find_under_25_goals,
                            self.find_over_15_goals,
                            self.find_over_05_goals
                        ]:
                            alt_prediction = func(markets)
                            if alt_prediction and alt_prediction["type"] not in used_prediction_types:
                                prediction = alt_prediction
                                logger.info(f"Prédiction alternative trouvée: {prediction['type']}")
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
        """Formate le message de prédiction pour Telegram dans un format plus concis."""
        now = datetime.now(self.timezone)
        date_str = now.strftime("%d/%m/%Y")
        
        message = f"🎲 *COUPON DU JOUR* | {date_str}\n\n"
        
        # Si aucune prédiction n'a été générée
        if not self.predictions:
            message += "_Aucune prédiction disponible aujourd'hui._"
            return message
        
        # Ajouter chaque prédiction au message
        for i, (match_id, pred) in enumerate(self.predictions.items()):
            # Calculer l'heure du match au format local
            start_time = datetime.fromtimestamp(pred["start_timestamp"], self.timezone).strftime("%H:%M")
            
            # Format concis pour chaque match
            message += f"• {pred['home_team']} vs {pred['away_team']} | {start_time}\n"
            message += f"  *{pred['type']}* ({pred['odds']})\n\n"
        
        # Ajouter la cote totale
        message += f"📊 *COTE TOTALE: {self.coupon_total_odds}*\n"
        message += f"_Misez 5% max. 🔞 Jeu responsable._"
        
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
