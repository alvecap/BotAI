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
        self.min_odds = 1.10  # Cote minimale pour les prédictions
        self.max_odds = 10.0  # Cote maximale pour éviter les paris trop risqués
        
        # Seuil pour considérer une cote comme "élevée" pour les doubles chances
        self.high_odds_threshold = 2.0  # Abaissé pour être plus sensible
        
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
            "under_35_goals",      # -3.5 buts
            "over_15_goals",       # +1.5 buts
            "over_25_goals",       # +2.5 buts
            "both_teams_to_score", # Les 2 équipes marquent
            "win_home",            # Victoire équipe domicile
            "win_away",            # Victoire équipe extérieur
            "double_chance_1X",    # 1X
            "double_chance_X2"     # X2
        ]
        
        # Configuration des poids pour les calculs de confiance
        self.league_weights = {
            "odds_weight": 0.4,        # Importance des cotes dans le calcul
            "league_type_weight": 0.3, # Importance du type de ligue
            "stability_weight": 0.3,   # Importance de la stabilité de la prédiction
        }
        
        # Coefficients de confiance de base pour chaque type de prédiction
        self.base_confidence = {
            "under_35_goals": 0.80,
            "over_15_goals": 0.75,
            "over_25_goals": 0.70,      
            "both_teams_to_score": 0.75, 
            "win_home": 0.65,            
            "win_away": 0.60,            
            "double_chance_1X": 0.85,
            "double_chance_X2": 0.80
        }
        
        # Paramètres de validation des équipes
        self.invalid_team_names = ["home", "away", "Home", "Away", "HOME", "AWAY", "1", "2", "X"]
        self.min_team_name_length = 3
        
        # Cotes moyennes attendues pour chaque type de prédiction (pour la stabilité)
        self.average_expected_odds = {
            "under_35_goals": 1.85,
            "over_15_goals": 1.07,
            "over_25_goals": 1.32,
            "both_teams_to_score": 2.71,
            "win_home": 1.90,
            "win_away": 2.50,
            "double_chance_1X": 1.40,
            "double_chance_X2": 1.60
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
    
    def is_valid_team_name(self, team_name):
        """
        Vérifie si le nom d'une équipe est valide.
        
        Règles:
        - Ne doit pas être vide
        - Ne doit pas être dans la liste des noms invalides (home, away, etc.)
        - Doit avoir une longueur minimale
        """
        if not team_name:
            return False
            
        if team_name.strip() in self.invalid_team_names:
            return False
            
        if len(team_name.strip()) < self.min_team_name_length:
            return False
            
        return True
    
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
                
                # Afficher un récapitulatif des prédictions dans la console
                self.print_coupon_summary()
                
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
                            
                            # Vérifier que les noms d'équipes sont valides
                            home_team = match.get("home_team")
                            away_team = match.get("away_team")
                            
                            if self.is_valid_team_name(home_team) and self.is_valid_team_name(away_team):
                                # Ajouter le match à notre liste
                                all_matches.append(match)
                                league_matches_count += 1
                            else:
                                logger.warning(f"Match ignoré - noms d'équipes invalides: {home_team} vs {away_team}")
            
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

    def get_teams_basic_odds(self, markets):
        """Récupère les cotes de base 1X2 pour les équipes."""
        home_odds = None
        draw_odds = None
        away_odds = None
        
        # Rechercher le marché 1X2 (ID "1")
        if "1" in markets:
            market = markets["1"]
            if market.get("name", "").lower() == "1x2":
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    if "home" in name and odds:
                        home_odds = odds
                    elif "draw" in name and odds:
                        draw_odds = odds
                    elif "away" in name and odds:
                        away_odds = odds
        
        return {
            "home": home_odds,
            "draw": draw_odds,
            "away": away_odds
        }

    # ============= MODÈLES DE CALCUL AVANCÉS POUR CHAQUE TYPE DE PRÉDICTION =============
    def find_under_35_goals(self, markets):
        """Modèle de calcul pour la prédiction Under 3.5 buts."""
        result = {
            "type": "-3.5 buts",
            "odds": None,
            "confidence": 0,
            "stability": 0
        }
        
        # Stocker toutes les cotes trouvées pour pouvoir les vérifier
        found_odds = []
        
        # Vérifier dans "Total" (ID "17")
        if "17" in markets:
            market = markets["17"]
            if "total" in market.get("name", "").lower():
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    if "under" in name and "3.5" in name and odds:
                        # Vérifier que les cotes sont dans notre plage
                        if self.min_odds <= odds <= self.max_odds:
                            found_odds.append({"odds": odds, "name": name})
        
        # Vérifier aussi dans Asian Total (ID "99")
        if "99" in markets:
            market = markets["99"]
            if "asian total" in market.get("name", "").lower():
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    if "under" in name and "3.5" in name and odds:
                        # Vérifier que les cotes sont dans notre plage
                        if self.min_odds <= odds <= self.max_odds:
                            found_odds.append({"odds": odds, "name": name})
        
        # Si plusieurs cotes sont trouvées, prendre la plus fiable
        if found_odds:
            # Trier par proximité avec la cote moyenne attendue
            found_odds.sort(key=lambda x: abs(x["odds"] - self.average_expected_odds["under_35_goals"]))
            
            # Prendre la meilleure cote
            best_odds = found_odds[0]["odds"]
            
            # Calculer la confiance basée sur les cotes
            odds_confidence = 1.0 - ((best_odds - self.min_odds) / (self.max_odds - self.min_odds))
            odds_confidence = max(0.5, min(0.95, odds_confidence))
            
            # Calculer la stabilité
            stability = 1.0 - min(1.0, abs(best_odds - self.average_expected_odds["under_35_goals"]) / self.average_expected_odds["under_35_goals"])
            
            # Stocker les cotes et la confiance brute
            result["odds"] = best_odds
            result["raw_confidence"] = odds_confidence
            result["stability"] = stability
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
        
        # Stocker toutes les cotes trouvées
        found_odds = []
        
        # Vérifier dans "Total" (ID "17")
        if "17" in markets:
            market = markets["17"]
            if "total" in market.get("name", "").lower():
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    if "over" in name and "1.5" in name and odds:
                        # Vérifier que les cotes sont dans notre plage
                        if self.min_odds <= odds <= self.max_odds:
                            found_odds.append({"odds": odds, "name": name})
        
        # Si plusieurs cotes sont trouvées, prendre la plus fiable
        if found_odds:
            # Trier par proximité avec la cote moyenne attendue
            found_odds.sort(key=lambda x: abs(x["odds"] - self.average_expected_odds["over_15_goals"]))
            
            # Prendre la meilleure cote
            best_odds = found_odds[0]["odds"]
            
            # Calculer la confiance basée sur les cotes
            odds_confidence = 1.0 - ((best_odds - self.min_odds) / (self.max_odds - self.min_odds))
            odds_confidence = max(0.6, min(0.92, odds_confidence))
            
            # Calculer la stabilité
            stability = 1.0 - min(1.0, abs(best_odds - self.average_expected_odds["over_15_goals"]) / self.average_expected_odds["over_15_goals"])
            
            # Stocker les cotes et la confiance brute
            result["odds"] = best_odds
            result["raw_confidence"] = odds_confidence
            result["stability"] = stability
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
        
        # Stocker toutes les cotes trouvées
        found_odds = []
        
        # Vérifier dans "Total" (ID "17")
        if "17" in markets:
            market = markets["17"]
            if "total" in market.get("name", "").lower():
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    if "over" in name and "2.5" in name and odds:
                        # Vérifier que les cotes sont dans notre plage
                        if self.min_odds <= odds <= self.max_odds:
                            found_odds.append({"odds": odds, "name": name})
        
        # Si plusieurs cotes sont trouvées, prendre la plus fiable
        if found_odds:
            # Trier par proximité avec la cote moyenne attendue
            found_odds.sort(key=lambda x: abs(x["odds"] - self.average_expected_odds["over_25_goals"]))
            
            # Prendre la meilleure cote
            best_odds = found_odds[0]["odds"]
            
            # Calculer la confiance basée sur les cotes
            odds_confidence = 1.0 - ((best_odds - self.min_odds) / (self.max_odds - self.min_odds))
            odds_confidence = max(0.55, min(0.90, odds_confidence))
            
            # Calculer la stabilité
            stability = 1.0 - min(1.0, abs(best_odds - self.average_expected_odds["over_25_goals"]) / self.average_expected_odds["over_25_goals"])
            
            # Stocker les cotes et la confiance brute
            result["odds"] = best_odds
            result["raw_confidence"] = odds_confidence
            result["stability"] = stability
            return result
        
        return None

    def find_both_teams_to_score(self, markets):
        """Modèle de calcul pour la prédiction 'Les deux équipes marquent'."""
        result = {
            "type": "Les 2 marquent",
            "odds": None,
            "confidence": 0,
            "stability": 0
        }
        
        # Stocker toutes les cotes trouvées
        found_odds = []
        
        # Vérifier dans "Both Teams To Score" (ID "19")
        if "19" in markets:
            market = markets["19"]
            if "both teams to score" in market.get("name", "").lower():
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    # Chercher "yes" pour les deux équipes marquent
                    if "yes" in name and odds:
                        # Vérifier que les cotes sont dans notre plage
                        if self.min_odds <= odds <= self.max_odds:
                            found_odds.append({"odds": odds, "name": name})
        
        # Si des cotes sont trouvées, prendre la plus fiable
        if found_odds:
            # Trier par proximité avec la cote moyenne attendue
            found_odds.sort(key=lambda x: abs(x["odds"] - self.average_expected_odds["both_teams_to_score"]))
            
            # Prendre la meilleure cote
            best_odds = found_odds[0]["odds"]
            
            # Calculer la confiance basée sur les cotes
            odds_confidence = 1.0 - ((best_odds - self.min_odds) / (self.max_odds - self.min_odds))
            odds_confidence = max(0.60, min(0.90, odds_confidence))
            
            # Calculer la stabilité
            stability = 1.0 - min(1.0, abs(best_odds - self.average_expected_odds["both_teams_to_score"]) / self.average_expected_odds["both_teams_to_score"])
            
            # Stocker les cotes et la confiance brute
            result["odds"] = best_odds
            result["raw_confidence"] = odds_confidence
            result["stability"] = stability
            return result
        
        return None
    
    def find_win_home(self, markets, basic_odds):
        """Modèle de calcul pour la prédiction 'Victoire équipe domicile'."""
        # Récupérer les cotes de base
        home_odds = basic_odds.get("home")
        
        # Vérifier si les cotes existent et sont dans notre plage
        if not home_odds or home_odds < self.min_odds or home_odds > self.max_odds:
            return None
        
        # Vérifier si c'est une cote attrayante (pas trop basse ni trop haute)
        if home_odds < 1.30 or home_odds > 5.0:
            return None
            
        result = {
            "type": "Victoire domicile",
            "odds": home_odds,
            "confidence": 0,
            "stability": 0
        }
        
        # Calculer la confiance basée sur les cotes (inversement proportionnelle)
        odds_confidence = 1.0 - ((home_odds - self.min_odds) / (5.0 - self.min_odds))
        odds_confidence = max(0.60, min(0.85, odds_confidence))
        
        # Calculer la stabilité
        stability = 1.0 - min(1.0, abs(home_odds - self.average_expected_odds["win_home"]) / self.average_expected_odds["win_home"])
        
        # Stocker les cotes et la confiance brute
        result["raw_confidence"] = odds_confidence
        result["stability"] = stability
        
        return result
    
    def find_win_away(self, markets, basic_odds):
        """Modèle de calcul pour la prédiction 'Victoire équipe extérieur'."""
        # Récupérer les cotes de base
        away_odds = basic_odds.get("away")
        
        # Vérifier si les cotes existent et sont dans notre plage
        if not away_odds or away_odds < self.min_odds or away_odds > self.max_odds:
            return None
        
        # Vérifier si c'est une cote attrayante (pas trop basse ni trop haute)
        if away_odds < 1.30 or away_odds > 5.0:
            return None
            
        result = {
            "type": "Victoire extérieur",
            "odds": away_odds,
            "confidence": 0,
            "stability": 0
        }
        
        # Calculer la confiance basée sur les cotes (inversement proportionnelle)
        odds_confidence = 1.0 - ((away_odds - self.min_odds) / (5.0 - self.min_odds))
        odds_confidence = max(0.55, min(0.80, odds_confidence))
        
        # Calculer la stabilité
        stability = 1.0 - min(1.0, abs(away_odds - self.average_expected_odds["win_away"]) / self.average_expected_odds["win_away"])
        
        # Stocker les cotes et la confiance brute
        result["raw_confidence"] = odds_confidence
        result["stability"] = stability
        
        return result

    def find_double_chance_1X(self, markets, basic_odds):
        """
        Modèle de calcul pour la prédiction Double Chance 1X.
        On predit une double chance si cette equipe peut potentiellement gagner ce match mais sa cote semble trop grande.
        """
        # Récupérer les cotes de base
        home_odds = basic_odds.get("home")
        draw_odds = basic_odds.get("draw")
        
        # Vérifier si les cotes existent
        if not home_odds or not draw_odds:
            return None
        
        # NOUVEAU: Ajout d'une vérification plus sophistiquée pour les doubles chances
        # On donne une double chance 1X quand:
        # 1. L'équipe à domicile a une cote élevée (>2.0) mais pas trop élevée (<5.0)
        # 2. La cote du nul est inférieure à la cote de l'équipe à domicile * 1.5 (pour éviter les cas trop déséquilibrés)
        if not (2.0 <= home_odds <= 5.0 and draw_odds <= home_odds * 1.5):
            return None
            
        result = {
            "type": "1X",
            "odds": None,
            "confidence": 0,
            "stability": 0
        }
        
        # Stocker toutes les cotes trouvées
        found_odds = []
        
        # Vérifier dans "Double Chance" (ID "8")
        if "8" in markets:
            market = markets["8"]
            if "double chance" in market.get("name", "").lower():
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    # On cherche "home or x"
                    if ("home or x" in name or "1x" in name.replace(" ", "")) and odds:
                        # Vérifier que les cotes sont dans notre plage
                        if self.min_odds <= odds <= self.max_odds:
                            found_odds.append({"odds": odds, "name": name})
        
        # Si des cotes sont trouvées, prendre la plus fiable
        if found_odds:
            # Trier par proximité avec la cote moyenne attendue
            found_odds.sort(key=lambda x: abs(x["odds"] - self.average_expected_odds["double_chance_1X"]))
            
            # Prendre la meilleure cote
            best_odds = found_odds[0]["odds"]
            
            # Calculer la confiance basée sur les cotes
            odds_confidence = 1.0 - ((best_odds - self.min_odds) / (self.max_odds - self.min_odds))
            odds_confidence = max(0.6, min(0.92, odds_confidence))
            
            # Calculer la stabilité
            stability = 1.0 - min(1.0, abs(best_odds - self.average_expected_odds["double_chance_1X"]) / self.average_expected_odds["double_chance_1X"])
            
            # Stocker les cotes et la confiance brute
            result["odds"] = best_odds
            result["raw_confidence"] = odds_confidence
            result["stability"] = stability
            return result
        
        return None

    def find_double_chance_X2(self, markets, basic_odds):
        """
        Modèle de calcul pour la prédiction Double Chance X2.
        On predit une double chance si cette equipe peut potentiellement gagner ce match mais sa cote semble trop grande.
        """
        # Récupérer les cotes de base
        away_odds = basic_odds.get("away")
        draw_odds = basic_odds.get("draw")
        
        # Vérifier si les cotes existent
        if not away_odds or not draw_odds:
            return None
        
        # NOUVEAU: Ajout d'une vérification plus sophistiquée pour les doubles chances
        # On donne une double chance X2 quand:
        # 1. L'équipe à l'extérieur a une cote élevée (>2.0) mais pas trop élevée (<5.0)
        # 2. La cote du nul est inférieure à la cote de l'équipe à l'extérieur * 1.5 (pour éviter les cas trop déséquilibrés)
        if not (2.0 <= away_odds <= 5.0 and draw_odds <= away_odds * 1.5):
            return None
            
        result = {
            "type": "X2",
            "odds": None,
            "confidence": 0,
            "stability": 0
        }
        
        # Stocker toutes les cotes trouvées
        found_odds = []
        
        # Vérifier dans "Double Chance" (ID "8")
        if "8" in markets:
            market = markets["8"]
            if "double chance" in market.get("name", "").lower():
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    # On cherche "away or x"
                    if ("away or x" in name or "x2" in name.replace(" ", "")) and odds:
                        # Vérifier que les cotes sont dans notre plage
                        if self.min_odds <= odds <= self.max_odds:
                            found_odds.append({"odds": odds, "name": name})
        
        # Si des cotes sont trouvées, prendre la plus fiable
        if found_odds:
            # Trier par proximité avec la cote moyenne attendue
            found_odds.sort(key=lambda x: abs(x["odds"] - self.average_expected_odds["double_chance_X2"]))
            
            # Prendre la meilleure cote
            best_odds = found_odds[0]["odds"]
            
            # Calculer la confiance basée sur les cotes
            odds_confidence = 1.0 - ((best_odds - self.min_odds) / (self.max_odds - self.min_odds))
            odds_confidence = max(0.55, min(0.88, odds_confidence))
            
            # Calculer la stabilité
            stability = 1.0 - min(1.0, abs(best_odds - self.average_expected_odds["double_chance_X2"]) / self.average_expected_odds["double_chance_X2"])
            
            # Stocker les cotes et la confiance brute
            result["odds"] = best_odds
            result["raw_confidence"] = odds_confidence
            result["stability"] = stability
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
            # Les ligues à faible scoring favorisent les "under" et défavorisent les "over" et "btts"
            if prediction_type == "-3.5 buts":
                league_factor = 1.15
            elif prediction_type in ["+1.5 buts", "+2.5 buts", "Les 2 marquent"]:
                league_factor = 0.85
        
        elif league_profile == "high":
            # Les ligues à fort scoring favorisent les "over" et "btts", et défavorisent les "under"
            if prediction_type == "-3.5 buts":
                league_factor = 0.85
            elif prediction_type in ["+1.5 buts", "+2.5 buts", "Les 2 marquent"]:
                league_factor = 1.15
        
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

    def log_available_markets(self, markets):
        """Fonction de debug pour afficher tous les marchés disponibles"""
        logger.info("=== MARCHÉS DISPONIBLES ===")
        for market_id, market in markets.items():
            market_name = market.get("name", "Sans nom")
            logger.info(f"ID: {market_id}, Nom: {market_name}")
            
            # Afficher quelques exemples d'issues pour ce marché
            for i, outcome in enumerate(market.get("outcomes", [])[:3]):
                outcome_name = outcome.get("name", "Sans nom")
                outcome_odds = outcome.get("odds", "?")
                logger.info(f"  - Outcome {i+1}: {outcome_name}, Cote: {outcome_odds}")
            
            # S'il y a plus de 3 issues, afficher combien il en reste
            if len(market.get("outcomes", [])) > 3:
                remaining = len(market.get("outcomes", [])) - 3
                logger.info(f"  + {remaining} autres issues...")

    def generate_match_predictions(self, match_id, markets, league_name, home_team, away_team):
        """
        Génère toutes les prédictions possibles pour un match spécifique,
        calcule leur confiance et les trie par niveau de confiance.
        """
        # Debug: afficher les marchés disponibles
        self.log_available_markets(markets)
        
        # Récupérer les cotes de base pour plusieurs types de prédictions
        basic_odds = self.get_teams_basic_odds(markets)
        
        logger.info(f"Cotes de base: Home={basic_odds.get('home')}, Draw={basic_odds.get('draw')}, Away={basic_odds.get('away')}")
        
        # Liste des prédictions possibles
        all_predictions = []
        
        # 1. Under 3.5 buts
        prediction = self.find_under_35_goals(markets)
        if prediction:
            prediction_with_confidence = self.calculate_prediction_confidence(prediction, league_name)
            if prediction_with_confidence:
                all_predictions.append(prediction_with_confidence)
        
        # 2. Over 1.5 buts
        prediction = self.find_over_15_goals(markets)
        if prediction:
            prediction_with_confidence = self.calculate_prediction_confidence(prediction, league_name)
            if prediction_with_confidence:
                all_predictions.append(prediction_with_confidence)
        
        # 3. Over 2.5 buts
        prediction = self.find_over_25_goals(markets)
        if prediction:
            prediction_with_confidence = self.calculate_prediction_confidence(prediction, league_name)
            if prediction_with_confidence:
                all_predictions.append(prediction_with_confidence)
        
        # 4. Both Teams To Score
        prediction = self.find_both_teams_to_score(markets)
        if prediction:
            prediction_with_confidence = self.calculate_prediction_confidence(prediction, league_name)
            if prediction_with_confidence:
                all_predictions.append(prediction_with_confidence)
        
        # 5. Victoire domicile
        prediction = self.find_win_home(markets, basic_odds)
        if prediction:
            prediction_with_confidence = self.calculate_prediction_confidence(prediction, league_name)
            if prediction_with_confidence:
                all_predictions.append(prediction_with_confidence)
        
        # 6. Victoire extérieur
        prediction = self.find_win_away(markets, basic_odds)
        if prediction:
            prediction_with_confidence = self.calculate_prediction_confidence(prediction, league_name)
            if prediction_with_confidence:
                all_predictions.append(prediction_with_confidence)
        
        # 7. Double Chance 1X
        prediction = self.find_double_chance_1X(markets, basic_odds)
        if prediction:
            prediction_with_confidence = self.calculate_prediction_confidence(prediction, league_name)
            if prediction_with_confidence:
                all_predictions.append(prediction_with_confidence)
        
        # 8. Double Chance X2
        prediction = self.find_double_chance_X2(markets, basic_odds)
        if prediction:
            prediction_with_confidence = self.calculate_prediction_confidence(prediction, league_name)
            if prediction_with_confidence:
                all_predictions.append(prediction_with_confidence)
        
        # Trier les prédictions par niveau de confiance (décroissant)
        all_predictions.sort(key=lambda x: x["confidence"], reverse=True)
        
        # Debug: afficher les prédictions trouvées
        logger.info(f"Nombre de prédictions générées: {len(all_predictions)}")
        for i, pred in enumerate(all_predictions):
            logger.info(f"Prédiction {i+1}: {pred['type']}, Cote: {pred['odds']}, Confiance: {pred['confidence']:.2f}")
        
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
            
            # VÉRIFICATION SUPPLÉMENTAIRE des noms d'équipes
            if not self.is_valid_team_name(home_team) or not self.is_valid_team_name(away_team):
                logger.warning(f"Match ignoré - noms d'équipes invalides: {home_team} vs {away_team}")
                continue
                
            logger.info(f"Analyse du match {home_team} vs {away_team} (ID: {match_id})...")
            
            # Récupérer les cotes pour ce match
            markets = self.get_match_odds(match_id)
            
            if not markets:
                logger.warning(f"Pas de cotes disponibles pour {home_team} vs {away_team}, match ignoré")
                continue
            
            # Générer toutes les prédictions possibles pour ce match
            all_predictions = self.generate_match_predictions(match_id, markets, league_name, home_team, away_team)
            
            # Si aucune prédiction n'a été trouvée, passer au match suivant
            if not all_predictions:
                logger.warning(f"Aucune prédiction fiable trouvée pour {home_team} vs {away_team}")
                continue
            
            # Vérifier qu'aucune cote n'est trop élevée ou trop basse
            valid_predictions = [p for p in all_predictions if self.min_odds <= p.get("odds", 0) <= self.max_odds]
            
            if not valid_predictions:
                logger.warning(f"Toutes les cotes pour {home_team} vs {away_team} sont en dehors de la plage acceptable, match ignoré")
                continue
                
            # Mettre à jour la liste avec uniquement les prédictions valides
            all_predictions = valid_predictions
            
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
                    if prediction_type == "-3.5 buts":
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
    
    def print_coupon_summary(self):
        """Affiche un récapitulatif du coupon dans la console."""
        if not self.predictions:
            logger.info("=== AUCUNE PRÉDICTION GÉNÉRÉE ===")
            return
        
        logger.info("\n" + "=" * 80)
        logger.info("=== RÉCAPITULATIF DU COUPON ===")
        logger.info("=" * 80)
        
        for i, (match_id, pred) in enumerate(self.predictions.items()):
            # Calculer l'heure du match au format local
            start_time = datetime.fromtimestamp(pred["start_timestamp"], self.timezone).strftime("%H:%M")
            
            logger.info(f"MATCH {i+1}: {pred['home_team']} vs {pred['away_team']}")
            logger.info(f"Ligue: {pred['league_name']}")
            logger.info(f"Heure: {start_time}")
            logger.info(f"Prédiction: {pred['type']}")
            logger.info(f"Cote: {pred['odds']}")
            logger.info(f"Confiance: {pred['confidence']:.2f}")
            logger.info("-" * 50)
        
        logger.info(f"COTE TOTALE DU COUPON: {self.coupon_total_odds}")
        logger.info("=" * 80 + "\n")
    
    def format_prediction_message(self):
        """Formate le message de prédiction pour Telegram avec mise en forme Markdown améliorée."""
        now = datetime.now(self.timezone)
        date_str = now.strftime("%d/%m/%Y")
        
        # Titre en gras avec émojis
        message = "🔮 *COUPON DU JOUR* 🔮\n"
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
            
            # Nom de la ligue en MAJUSCULES
            message += f"🏆 *{pred['league_name'].upper()}*\n"
            
            # Équipes sur une ligne
            message += f"⚽️ *{pred['home_team']} vs {pred['away_team']}*\n"
            
            # Heure sur une nouvelle ligne
            message += f"⏰ Heure: {start_time}\n"
            
            # Prédiction en gras et plus visible
            message += f"🎯 *PRÉDICTION: {pred['type']}*\n"
            
            # Cote
            message += f"💰 Cote: {pred['odds']}\n"
        
        # Ajouter la cote totale en gras
        message += f"----------------------------\n\n"
        message += f"📊 *COTE TOTALE: {self.coupon_total_odds}*\n\n"
        
        # Conseils en italique
        message += f"💡 _Misez toujours 5% de votre capital_\n"
        message += f"🔞 _Pariez de façon responsable._"
        
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
