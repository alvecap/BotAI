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
import math

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
        
        # Paramètres des prédictions
        self.min_odds = 1.15  # Cote minimale pour les prédictions
        self.max_odds = 10.0  # Cote maximale pour éviter les paris trop risqués
        
        # Catégorisation des championnats par niveau de scoring
        self.low_scoring_leagues = [
            "ghana", "nigeria", "kenya", "tanzania", "ethiopia", "south africa", 
            "morocco", "algeria", "tunisia", "cameroon", "ivory coast", "senegal", "egypt",
            "belarus", "estonia", "latvia", "lithuania", "uzbekistan", "kazakhstan",
            "peru", "bolivia", "venezuela", "ecuador", "women"  # Les ligues féminines ont généralement moins de buts
        ]
        
        self.high_scoring_leagues = [
            "germany", "bundesliga", "netherlands", "england premier league", 
            "austria", "belgium", "switzerland", "sweden", "norway"
        ]
        
        # Liste des IDs de ligue connus qui fonctionnent avec l'API
        self.league_ids = [1, 118, 148, 127, 110, 136, 251, 252, 253, 301, 302, 303, 304]
        
        # Types de prédictions à considérer
        self.prediction_types = [
            "under_25_goals", "under_35_goals", "under_45_goals",
            "over_05_goals", "over_15_goals", "over_25_goals",
            "btts_yes", "btts_no", "double_chance_1X", "double_chance_X2", "double_chance_12"
        ]
        
        # Configuration des poids pour les calculs de confiance
        self.league_weights = {
            "odds_weight": 0.4,        # Importance des cotes dans le calcul
            "league_type_weight": 0.3, # Importance du type de ligue
            "stability_weight": 0.3,   # Importance de la stabilité de la prédiction
        }
        
        # Coefficients de confiance de base pour chaque type de prédiction
        self.base_confidence = {
            "under_25_goals": 0.75,
            "under_35_goals": 0.80,
            "under_45_goals": 0.85,
            "over_05_goals": 0.90,
            "over_15_goals": 0.75,
            "over_25_goals": 0.65,
            "btts_yes": 0.70,
            "btts_no": 0.70,
            "double_chance_1X": 0.85,
            "double_chance_X2": 0.80,
            "double_chance_12": 0.75
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
    
    def is_high_scoring_league(self, league_name):
        """Détermine si une ligue est considérée comme à fort scoring."""
        if not league_name:
            return False
            
        league_name_lower = league_name.lower()
        return any(league in league_name_lower for league in self.high_scoring_leagues)
    
    def get_league_scoring_profile(self, league_name):
        """Retourne un profil de scoring pour une ligue (low, medium, high)."""
        if self.is_low_scoring_league(league_name):
            return "low"
        elif self.is_high_scoring_league(league_name):
            return "high"
        else:
            return "medium"
    
    def select_matches(self, all_matches):
        """Sélectionne des matchs pour les prédictions avec priorité aux ligues à faible scoring."""
        if not all_matches:
            logger.warning("Aucun match disponible pour la sélection.")
            return
        
        # Trier les matchs en catégories par profil de scoring
        low_scoring_matches = []
        medium_scoring_matches = []
        high_scoring_matches = []
        
        for match in all_matches:
            league_name = match.get("league", "")
            
            if self.is_low_scoring_league(league_name):
                low_scoring_matches.append(match)
            elif self.is_high_scoring_league(league_name):
                high_scoring_matches.append(match)
            else:
                medium_scoring_matches.append(match)
        
        logger.info(f"Matchs de championnats à faible scoring disponibles: {len(low_scoring_matches)}")
        logger.info(f"Matchs de championnats à scoring moyen disponibles: {len(medium_scoring_matches)}")
        logger.info(f"Matchs de championnats à fort scoring disponibles: {len(high_scoring_matches)}")
        
        # Donner la priorité aux matchs de ligues à faible scoring (60%), puis scoring moyen (30%), puis fort scoring (10%)
        max_matches = min(5, len(all_matches))
        
        # Calculer les quotas pour chaque catégorie de match
        low_scoring_quota = max(1, round(max_matches * 0.6))
        medium_scoring_quota = max(1, round(max_matches * 0.3))
        high_scoring_quota = max_matches - low_scoring_quota - medium_scoring_quota
        
        # Ajuster les quotas si certaines catégories n'ont pas assez de matchs
        if len(low_scoring_matches) < low_scoring_quota:
            shortage = low_scoring_quota - len(low_scoring_matches)
            medium_scoring_quota += shortage // 2
            high_scoring_quota += shortage - (shortage // 2)
            low_scoring_quota = len(low_scoring_matches)
        
        if len(medium_scoring_matches) < medium_scoring_quota:
            shortage = medium_scoring_quota - len(medium_scoring_matches)
            high_scoring_quota += shortage
            medium_scoring_quota = len(medium_scoring_matches)
        
        if len(high_scoring_matches) < high_scoring_quota:
            shortage = high_scoring_quota - len(high_scoring_matches)
            medium_scoring_quota += shortage
            high_scoring_quota = len(high_scoring_matches)
            
            if len(medium_scoring_matches) < medium_scoring_quota:
                medium_scoring_quota = len(medium_scoring_matches)
        
        # Sélectionner les matchs selon les quotas
        selected_low_scoring = random.sample(low_scoring_matches, min(low_scoring_quota, len(low_scoring_matches))) if low_scoring_matches else []
        selected_medium_scoring = random.sample(medium_scoring_matches, min(medium_scoring_quota, len(medium_scoring_matches))) if medium_scoring_matches else []
        selected_high_scoring = random.sample(high_scoring_matches, min(high_scoring_quota, len(high_scoring_matches))) if high_scoring_matches else []
        
        # Combiner les sélections
        self.selected_matches = selected_low_scoring + selected_medium_scoring + selected_high_scoring
        
        logger.info(f"=== SÉLECTION DE {len(self.selected_matches)} MATCH(S) POUR LES PRÉDICTIONS ===")
        logger.info(f"Dont {len(selected_low_scoring)} matchs à faible scoring, {len(selected_medium_scoring)} à scoring moyen et {len(selected_high_scoring)} à fort scoring")
        
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

    # ============= MODÈLES DE CALCUL AVANCÉS POUR CHAQUE TYPE DE PRÉDICTION =============
    
    def find_under_25_goals(self, markets):
        """Modèle de calcul pour la prédiction Under 2.5 buts."""
        result = {
            "type": "-2.5 buts",
            "odds": None,
            "confidence": 0,
            "stability": 0
        }
        
        # Rechercher le marché Total (Under 2.5)
        for market_id, market in markets.items():
            market_name = market.get("name", "").lower()
            
            if "total" in market_name and not "team" in market_name:
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    if "under" in name and "2.5" in name and odds:
                        if self.min_odds <= odds <= self.max_odds:
                            result["odds"] = odds
                            
                            # Calculer la confiance basée sur les cotes
                            # Plus les cotes sont basses, plus la confiance est élevée
                            odds_confidence = 1.0 - ((odds - self.min_odds) / (self.max_odds - self.min_odds))
                            odds_confidence = max(0.5, min(0.95, odds_confidence))
                            
                            # La stabilité dépend de l'écart avec les cotes moyennes pour ce type de pari
                            # (ici on simule une valeur, mais en production on comparerait avec des moyennes historiques)
                            avg_under_25_odds = 1.85  # Cote moyenne fictive pour under 2.5
                            stability = 1.0 - min(1.0, abs(odds - avg_under_25_odds) / avg_under_25_odds)
                            result["stability"] = stability
                            
                            # Stocker les cotes et la confiance brute
                            result["odds"] = odds
                            result["raw_confidence"] = odds_confidence
                            return result
        
        return None

    def find_under_35_goals(self, markets):
        """Modèle de calcul pour la prédiction Under 3.5 buts."""
        result = {
            "type": "-3.5 buts",
            "odds": None,
            "confidence": 0,
            "stability": 0
        }
        
        for market_id, market in markets.items():
            market_name = market.get("name", "").lower()
            
            if "total" in market_name and not "team" in market_name:
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    if "under" in name and "3.5" in name and odds:
                        if self.min_odds <= odds <= self.max_odds:
                            # Calculer la confiance basée sur les cotes
                            odds_confidence = 1.0 - ((odds - self.min_odds) / (self.max_odds - self.min_odds))
                            odds_confidence = max(0.5, min(0.95, odds_confidence))
                            
                            # Calculer la stabilité
                            avg_under_35_odds = 1.45  # Cote moyenne fictive pour under 3.5
                            stability = 1.0 - min(1.0, abs(odds - avg_under_35_odds) / avg_under_35_odds)
                            result["stability"] = stability
                            
                            # Stocker les cotes et la confiance brute
                            result["odds"] = odds
                            result["raw_confidence"] = odds_confidence
                            return result
        
        return None

    def find_under_45_goals(self, markets):
        """Modèle de calcul pour la prédiction Under 4.5 buts."""
        result = {
            "type": "-4.5 buts",
            "odds": None,
            "confidence": 0,
            "stability": 0
        }
        
        for market_id, market in markets.items():
            market_name = market.get("name", "").lower()
            
            if "total" in market_name and not "team" in market_name:
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    if "under" in name and "4.5" in name and odds:
                        if self.min_odds <= odds <= self.max_odds:
                            # Calculer la confiance basée sur les cotes
                            odds_confidence = 1.0 - ((odds - self.min_odds) / (self.max_odds - self.min_odds))
                            odds_confidence = max(0.6, min(0.95, odds_confidence))
                            
                            # Calculer la stabilité
                            avg_under_45_odds = 1.25  # Cote moyenne fictive pour under 4.5
                            stability = 1.0 - min(1.0, abs(odds - avg_under_45_odds) / avg_under_45_odds)
                            result["stability"] = stability
                            
                            # Stocker les cotes et la confiance brute
                            result["odds"] = odds
                            result["raw_confidence"] = odds_confidence
                            return result
        
        return None

    def find_over_05_goals(self, markets):
        """Modèle de calcul pour la prédiction Over 0.5 buts."""
        result = {
            "type": "+0.5 buts",
            "odds": None,
            "confidence": 0,
            "stability": 0
        }
        
        for market_id, market in markets.items():
            market_name = market.get("name", "").lower()
            
            if "total" in market_name and not "team" in market_name:
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    if "over" in name and "0.5" in name and odds:
                        if self.min_odds <= odds <= self.max_odds:
                            # Calculer la confiance basée sur les cotes
                            odds_confidence = 1.0 - ((odds - self.min_odds) / (self.max_odds - self.min_odds))
                            odds_confidence = max(0.7, min(0.98, odds_confidence))
                            
                            # Calculer la stabilité
                            avg_over_05_odds = 1.20  # Cote moyenne fictive pour over 0.5
                            stability = 1.0 - min(1.0, abs(odds - avg_over_05_odds) / avg_over_05_odds)
                            result["stability"] = stability
                            
                            # Stocker les cotes et la confiance brute
                            result["odds"] = odds
                            result["raw_confidence"] = odds_confidence
                            return result
        
        return None

    def find_over_15_goals(self, markets):
        """Modèle de calcul pour la prédiction Over 1.5 buts."""
        result = {
            "type": "+1.5 buts",
            "odds": None,
            "confidence": 0,
            "stability": 0
        }
        
        for market_id, market in markets.items():
            market_name = market.get("name", "").lower()
            
            if "total" in market_name and not "team" in market_name:
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    if "over" in name and "1.5" in name and odds:
                        if self.min_odds <= odds <= self.max_odds:
                            # Calculer la confiance basée sur les cotes
                            odds_confidence = 1.0 - ((odds - self.min_odds) / (self.max_odds - self.min_odds))
                            odds_confidence = max(0.6, min(0.92, odds_confidence))
                            
                            # Calculer la stabilité
                            avg_over_15_odds = 1.40  # Cote moyenne fictive pour over 1.5
                            stability = 1.0 - min(1.0, abs(odds - avg_over_15_odds) / avg_over_15_odds)
                            result["stability"] = stability
                            
                            # Stocker les cotes et la confiance brute
                            result["odds"] = odds
                            result["raw_confidence"] = odds_confidence
                            return result
        
        return None

    def find_over_25_goals(self, markets):
        """Modèle de calcul pour la prédiction Over 2.5 buts."""
        result = {
            "type": "+2.5 buts",
            "odds": None,
            "confidence": 0,
            "stability": 0
        }
        
        for market_id, market in markets.items():
            market_name = market.get("name", "").lower()
            
            if "total" in market_name and not "team" in market_name:
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    if "over" in name and "2.5" in name and odds:
                        if self.min_odds <= odds <= self.max_odds:
                            # Calculer la confiance basée sur les cotes
                            odds_confidence = 1.0 - ((odds - self.min_odds) / (self.max_odds - self.min_odds))
                            odds_confidence = max(0.55, min(0.90, odds_confidence))
                            
                            # Calculer la stabilité
                            avg_over_25_odds = 1.90  # Cote moyenne fictive pour over 2.5
                            stability = 1.0 - min(1.0, abs(odds - avg_over_25_odds) / avg_over_25_odds)
                            result["stability"] = stability
                            
                            # Stocker les cotes et la confiance brute
                            result["odds"] = odds
                            result["raw_confidence"] = odds_confidence
                            return result
        
        return None

    def find_btts_yes(self, markets):
        """Modèle de calcul pour la prédiction Les deux équipes marquent - Oui."""
        result = {
            "type": "Les 2 équipes marquent",
            "odds": None,
            "confidence": 0,
            "stability": 0
        }
        
        for market_id, market in markets.items():
            market_name = market.get("name", "").lower()
            
            if "both teams to score" in market_name:
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    if (name in ["yes", "oui"] or "yes" in name) and odds:
                        if self.min_odds <= odds <= self.max_odds:
                            # Calculer la confiance basée sur les cotes
                            odds_confidence = 1.0 - ((odds - self.min_odds) / (self.max_odds - self.min_odds))
                            odds_confidence = max(0.5, min(0.85, odds_confidence))
                            
                            # Calculer la stabilité
                            avg_btts_yes_odds = 1.85  # Cote moyenne fictive pour BTTS Yes
                            stability = 1.0 - min(1.0, abs(odds - avg_btts_yes_odds) / avg_btts_yes_odds)
                            result["stability"] = stability
                            
                            # Stocker les cotes et la confiance brute
                            result["odds"] = odds
                            result["raw_confidence"] = odds_confidence
                            return result
        
        return None

    def find_btts_no(self, markets):
        """Modèle de calcul pour la prédiction Les deux équipes marquent - Non."""
        result = {
            "type": "Les 2 équipes ne marquent pas",
            "odds": None,
            "confidence": 0,
            "stability": 0
        }
        
        for market_id, market in markets.items():
            market_name = market.get("name", "").lower()
            
            if "both teams to score" in market_name:
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    if (name in ["no", "non"] or "no" in name) and odds:
                        if self.min_odds <= odds <= self.max_odds:
                            # Calculer la confiance basée sur les cotes
                            odds_confidence = 1.0 - ((odds - self.min_odds) / (self.max_odds - self.min_odds))
                            odds_confidence = max(0.5, min(0.85, odds_confidence))
                            
                            # Calculer la stabilité
                            avg_btts_no_odds = 1.95  # Cote moyenne fictive pour BTTS No
                            stability = 1.0 - min(1.0, abs(odds - avg_btts_no_odds) / avg_btts_no_odds)
                            result["stability"] = stability
                            
                            # Stocker les cotes et la confiance brute
                            result["odds"] = odds
                            result["raw_confidence"] = odds_confidence
                            return result
        
        return None

    def find_double_chance_1X(self, markets):
        """Modèle de calcul pour la prédiction Double Chance 1X."""
        result = {
            "type": "1X",
            "odds": None,
            "confidence": 0,
            "stability": 0
        }
        
        for market_id, market in markets.items():
            market_name = market.get("name", "").lower()
            
            if "double chance" in market_name:
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "")
                    odds = outcome.get("odds")
                    
                    # On cherche 1X, Home Or X, HOME Or X, etc.
                    if ("1X" in name or "HOME Or X" in name or "HOME or X" in name or "home or x" in name) and odds:
                        if self.min_odds <= odds <= self.max_odds:
                            # Calculer la confiance basée sur les cotes
                            odds_confidence = 1.0 - ((odds - self.min_odds) / (self.max_odds - self.min_odds))
                            odds_confidence = max(0.6, min(0.92, odds_confidence))
                            
                            # Calculer la stabilité
                            avg_1X_odds = 1.50  # Cote moyenne fictive pour 1X
                            stability = 1.0 - min(1.0, abs(odds - avg_1X_odds) / avg_1X_odds)
                            result["stability"] = stability
                            
                            # Stocker les cotes et la confiance brute
                            result["odds"] = odds
                            result["raw_confidence"] = odds_confidence
                            return result
        
        return None

    def find_double_chance_X2(self, markets):
        """Modèle de calcul pour la prédiction Double Chance X2."""
        result = {
            "type": "X2",
            "odds": None,
            "confidence": 0,
            "stability": 0
        }
        
        for market_id, market in markets.items():
            market_name = market.get("name", "").lower()
            
            if "double chance" in market_name:
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "")
                    odds = outcome.get("odds")
                    
                    # On cherche X2, Away Or X, AWAY Or X, etc.
                    if ("X2" in name or "AWAY Or X" in name or "AWAY or X" in name or "away or x" in name) and odds:
                        if self.min_odds <= odds <= self.max_odds:
                            # Calculer la confiance basée sur les cotes
                            odds_confidence = 1.0 - ((odds - self.min_odds) / (self.max_odds - self.min_odds))
                            odds_confidence = max(0.55, min(0.88, odds_confidence))
                            
                            # Calculer la stabilité
                            avg_X2_odds = 1.75  # Cote moyenne fictive pour X2
                            stability = 1.0 - min(1.0, abs(odds - avg_X2_odds) / avg_X2_odds)
                            result["stability"] = stability
                            
                            # Stocker les cotes et la confiance brute
                            result["odds"] = odds
                            result["raw_confidence"] = odds_confidence
                            return result
        
        return None

    def find_double_chance_12(self, markets):
        """Modèle de calcul pour la prédiction Double Chance 12."""
        result = {
            "type": "12",
            "odds": None,
            "confidence": 0,
            "stability": 0
        }
        
        for market_id, market in markets.items():
            market_name = market.get("name", "").lower()
            
            if "double chance" in market_name:
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "")
                    odds = outcome.get("odds")
                    
                    # On cherche 12, Home Or Away, HOME Or AWAY, etc.
                    if ("12" in name or "HOME Or AWAY" in name or "HOME or AWAY" in name or "home or away" in name) and odds:
                        if self.min_odds <= odds <= self.max_odds:
                            # Calculer la confiance basée sur les cotes
                            odds_confidence = 1.0 - ((odds - self.min_odds) / (self.max_odds - self.min_odds))
                            odds_confidence = max(0.5, min(0.85, odds_confidence))
                            
                            # Calculer la stabilité
                            avg_12_odds = 1.25  # Cote moyenne fictive pour 12
                            stability = 1.0 - min(1.0, abs(odds - avg_12_odds) / avg_12_odds)
                            result["stability"] = stability
                            
                            # Stocker les cotes et la confiance brute
                            result["odds"] = odds
                            result["raw_confidence"] = odds_confidence
                            return result
        
        return None

    def calculate_prediction_confidence(self, prediction, league_name):
        """
        Calcule la confiance finale pour une prédiction en tenant compte de plusieurs facteurs:
        1. La confiance brute basée sur les cotes
        2. Le type de ligue (low scoring, high scoring, etc.)
        3. La stabilité de la prédiction
        """
        if not prediction:
            return None
            
        prediction_type = prediction["type"]
        raw_confidence = prediction.get("raw_confidence", 0.5)
        stability = prediction.get("stability", 0.7)
        
        # Ajustement selon le type de ligue
        league_profile = self.get_league_scoring_profile(league_name)
        league_factor = 1.0
        
        # Ajuster selon le type de prédiction et le profil de la ligue
        if league_profile == "low":
            # Les ligues à faible scoring favorisent les "under" et défavorisent les "over" et "btts_yes"
            if "buts" in prediction_type and "-" in prediction_type:  # Under goals
                league_factor = 1.15
            elif "buts" in prediction_type and "+" in prediction_type:  # Over goals
                league_factor = 0.85
            elif prediction_type == "Les 2 équipes marquent":  # BTTS Yes
                league_factor = 0.80
            elif prediction_type == "Les 2 équipes ne marquent pas":  # BTTS No
                league_factor = 1.20
        
        elif league_profile == "high":
            # Les ligues à fort scoring favorisent les "over" et "btts_yes" et défavorisent les "under"
            if "buts" in prediction_type and "-" in prediction_type:  # Under goals
                league_factor = 0.85
            elif "buts" in prediction_type and "+" in prediction_type:  # Over goals
                league_factor = 1.15
            elif prediction_type == "Les 2 équipes marquent":  # BTTS Yes
                league_factor = 1.15
            elif prediction_type == "Les 2 équipes ne marquent pas":  # BTTS No
                league_factor = 0.80
        
        # La confiance finale est une moyenne pondérée des différents facteurs
        weighted_confidence = (
            self.league_weights["odds_weight"] * raw_confidence +
            self.league_weights["league_type_weight"] * league_factor +
            self.league_weights["stability_weight"] * stability
        )
        
        # Normaliser entre 0 et 1, puis convertir en pourcentage
        confidence_percentage = min(0.98, weighted_confidence)
        
        # Stocker la confiance finale dans la prédiction
        prediction["confidence"] = confidence_percentage
        
        return prediction

    def generate_match_predictions(self, match_id, markets, league_name):
        """
        Génère toutes les prédictions possibles pour un match spécifique,
        calcule leur confiance et les trie par niveau de confiance.
        """
        # Liste des fonctions de prédiction à appliquer
        prediction_functions = [
            self.find_under_25_goals,
            self.find_under_35_goals,
            self.find_under_45_goals,
            self.find_over_05_goals,
            self.find_over_15_goals,
            self.find_over_25_goals,
            self.find_btts_yes,
            self.find_btts_no,
            self.find_double_chance_1X,
            self.find_double_chance_X2,
            self.find_double_chance_12
        ]
        
        # Générer toutes les prédictions possibles
        all_predictions = []
        
        for func in prediction_functions:
            prediction = func(markets)
            if prediction:
                # Calculer la confiance finale de la prédiction
                prediction_with_confidence = self.calculate_prediction_confidence(prediction, league_name)
                if prediction_with_confidence:
                    all_predictions.append(prediction_with_confidence)
        
        # Trier les prédictions par niveau de confiance (décroissant)
        all_predictions.sort(key=lambda x: x["confidence"], reverse=True)
        
        return all_predictions
    
    def generate_predictions(self):
        """
        Génère les meilleures prédictions pour les matchs sélectionnés 
        en choisissant la prédiction la plus fiable pour chaque match.
        """
        logger.info("=== GÉNÉRATION DES PRÉDICTIONS ===")
        
        # Liste des types de prédictions déjà utilisés
        used_prediction_types = []
        
        # Pour chaque match
        for match in self.selected_matches:
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
            
            # Générer toutes les prédictions possibles pour ce match
            all_predictions = self.generate_match_predictions(match_id, markets, league_name)
            
            # Si aucune prédiction n'a été trouvée, passer au match suivant
            if not all_predictions:
                logger.warning(f"Aucune prédiction fiable trouvée pour {home_team} vs {away_team}")
                continue
            
            # Sélectionner la meilleure prédiction en évitant les doublons
            selected_prediction = None
            
            # Essayer d'abord avec la prédiction de plus haute confiance
            for prediction in all_predictions:
                prediction_type = prediction["type"]
                
                # Si ce type de prédiction n'est pas déjà utilisé, le sélectionner
                if prediction_type not in used_prediction_types:
                    selected_prediction = prediction
                    used_prediction_types.append(prediction_type)
                    break
            
            # Si toutes les prédictions avec haute confiance sont déjà utilisées,
            # accepter un doublon pour les prédictions under dans les ligues à faible scoring
            if not selected_prediction and self.is_low_scoring_league(league_name):
                for prediction in all_predictions:
                    prediction_type = prediction["type"]
                    
                    # Accepter les under goals comme répétitions pour les ligues à faible scoring
                    if ("buts" in prediction_type and "-" in prediction_type) or prediction_type == "Les 2 équipes ne marquent pas":
                        selected_prediction = prediction
                        break
            
            # Si toujours pas de prédiction, prendre la prédiction de plus haute confiance
            # même si elle est déjà utilisée
            if not selected_prediction and all_predictions:
                selected_prediction = all_predictions[0]
                
            # Si une prédiction a été trouvée
            if selected_prediction:
                # Ajouter les informations du match
                selected_prediction["match_id"] = match_id
                selected_prediction["home_team"] = home_team
                selected_prediction["away_team"] = away_team
                selected_prediction["league_name"] = league_name
                selected_prediction["start_timestamp"] = match.get("start_timestamp", 0)
                
                # Stocker la prédiction
                self.predictions[match_id] = selected_prediction
                
                logger.info(f"  Prédiction pour {home_team} vs {away_team}: {selected_prediction['type']} (Cote: {selected_prediction['odds']}, Confiance: {selected_prediction['confidence']:.2f})")
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
        
        message = f"🔮 *COUPON DU JOUR* 🔮\n"
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
            
            message += f"🏆 {pred['league_name'].upper()}\n"
            message += f"⚽ {pred['home_team']} vs {pred['away_team']} | {start_time}\n"
            message += f"🎯 Prédiction: {pred['type']}\n"
            message += f"💰 Cote: {pred['odds']}\n"
        
        # Ajouter la cote totale
        message += f"----------------------------\n\n"
        message += f"📊 *COTE TOTALE: {self.coupon_total_odds}*\n\n"
        
        # Conseil de bankroll et jeu responsable
        message += f"💡 *Misez toujours 5% de votre capital*\n"
        message += f"🔞 *Pariez de façon responsable.*"
        
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
