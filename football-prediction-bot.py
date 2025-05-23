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
        
        # RÈGLES CLARIFIÉES SELON VOS INSTRUCTIONS
        self.max_odds_by_goals = {
            1.5: 1.99,   # Over 1.5 (barème équipes)
            2.5: 2.50,   # Over 2.5 (si les 2 équipes respectent 1.5)
            3.5: 3.00    # Over 3.5 (cote max 3.00 au lieu de 3.80)
        }
        
        # Cote minimale acceptée pour toute prédiction
        self.min_odds_threshold = 1.10
        
        # Catégorisation des championnats par niveau de scoring
        self.low_scoring_leagues = [
            "ghana", "nigeria", "kenya", "tanzania", "ethiopia", "south africa", 
            "morocco", "algeria", "tunisia", "cameroon", "ivory coast", "senegal", "egypt",
            "belarus", "estonia", "latvia", "lithuania", "uzbekistan", "kazakhstan",
            "peru", "bolivia", "venezuela", "ecuador", "women"
        ]
        
        self.high_scoring_leagues = [
            "germany", "bundesliga", "netherlands", "england premier league", 
            "austria", "belgium", "switzerland", "sweden", "norway"
        ]
        
        # Liste des IDs de ligue connus qui fonctionnent avec l'API
        self.league_ids = [1, 118, 148, 127, 110, 136, 251, 252, 253, 301, 302, 303, 304]
        
        # Paramètres de validation des équipes
        self.invalid_team_names = ["home", "away", "Home", "Away", "HOME", "AWAY", "1", "2", "X"]
        self.min_team_name_length = 3
    
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
        """Vérifie si le nom d'une équipe est valide."""
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
            # Sélectionner des matchs pour les prédictions (6 matchs)
            self.select_matches(all_matches)
            
            # Générer des prédictions avec les modèles corrigés
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
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
            except Exception as e:
                logger.error(f"Erreur de connexion (tentative {attempt+1}/{max_retries}): {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
        
        logger.error(f"Échec de la requête après {max_retries} tentatives: {endpoint}")
        return None
    
    def get_todays_matches(self):
        """Récupère les matchs du jour en utilisant les IDs de ligue connus."""
        now = datetime.now(self.timezone)
        now_timestamp = int(now.timestamp())
        
        today_start = datetime(now.year, now.month, now.day, 0, 0, 0).replace(tzinfo=self.timezone)
        today_end = datetime(now.year, now.month, now.day, 23, 59, 59).replace(tzinfo=self.timezone)
        
        start_timestamp = int(today_start.timestamp())
        end_timestamp = int(today_end.timestamp())
        
        logger.info(f"Recherche de matchs pour aujourd'hui ({now.strftime('%d/%m/%Y')})...")
        
        all_matches = []
        
        for league_id in self.league_ids:
            endpoint = f"/matches?sport_id=1&league_id={league_id}&mode=line&lng=en"
            response = self.make_api_request(endpoint)
            
            if not response or response.get("status") != "success":
                continue
            
            matches = response.get("data", [])
            
            if not isinstance(matches, list):
                continue
            
            for match in matches:
                match_timestamp = match.get("start_timestamp", 0)
                
                if start_timestamp <= match_timestamp <= end_timestamp:
                    if match_timestamp > now_timestamp:
                        if (match.get("home_team") and 
                            match.get("away_team") and 
                            match.get("league") and 
                            match.get("id")):
                            
                            home_team = match.get("home_team")
                            away_team = match.get("away_team")
                            
                            if self.is_valid_team_name(home_team) and self.is_valid_team_name(away_team):
                                all_matches.append(match)
            
            time.sleep(0.5)
        
        logger.info(f"Total des matchs trouvés: {len(all_matches)}")
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
    
    def select_matches(self, all_matches):
        """Sélectionne 6 matchs pour les prédictions."""
        if not all_matches:
            logger.warning("Aucun match disponible pour la sélection.")
            return
        
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
        
        max_matches = min(6, len(all_matches))
        
        low_scoring_quota = max(1, round(max_matches * 0.6))
        medium_scoring_quota = max(1, round(max_matches * 0.3))
        high_scoring_quota = max_matches - low_scoring_quota - medium_scoring_quota
        
        # Ajuster les quotas si nécessaire
        if len(low_scoring_matches) < low_scoring_quota:
            shortage = low_scoring_quota - len(low_scoring_matches)
            medium_scoring_quota += shortage // 2
            high_scoring_quota += shortage - (shortage // 2)
            low_scoring_quota = len(low_scoring_matches)
        
        selected_low_scoring = random.sample(low_scoring_matches, min(low_scoring_quota, len(low_scoring_matches))) if low_scoring_matches else []
        selected_medium_scoring = random.sample(medium_scoring_matches, min(medium_scoring_quota, len(medium_scoring_matches))) if medium_scoring_matches else []
        selected_high_scoring = random.sample(high_scoring_matches, min(high_scoring_quota, len(high_scoring_matches))) if high_scoring_matches else []
        
        self.selected_matches = selected_low_scoring + selected_medium_scoring + selected_high_scoring
        
        logger.info(f"=== SÉLECTION DE {len(self.selected_matches)} MATCH(S) ===")
        
        for i, match in enumerate(self.selected_matches):
            start_timestamp = match.get("start_timestamp", 0)
            start_time = datetime.fromtimestamp(start_timestamp, self.timezone)
            home_team = match.get("home_team", "Équipe inconnue")
            away_team = match.get("away_team", "Équipe inconnue")
            league_name = match.get("league", "Ligue inconnue")
            
            logger.info(f"Match {i+1}: {home_team} vs {away_team} - {league_name}")
    
    def get_match_odds(self, match_id):
        """Récupère les cotes pour un match spécifique."""
        endpoint = f"/matches/{match_id}/markets?mode=line&lng=en"
        response = self.make_api_request(endpoint)
        
        if not response or response.get("status") != "success":
            return None
        
        return response.get("data", {})

    # ============= FONCTIONS D'EXTRACTION =============
    
    def extract_team_totals(self, markets):
        """Extrait les totaux individuels des équipes."""
        home_totals = {}
        away_totals = {}
        
        # Total 1 (ID "15") - Équipe domicile
        if "15" in markets:
            market = markets["15"]
            for outcome in market.get("outcomes", []):
                name = outcome.get("name", "").lower()
                odds = outcome.get("odds")
                
                if "over" in name and odds and odds >= self.min_odds_threshold:
                    if "1.5" in name:
                        home_totals[1.5] = odds
                    elif "2.5" in name:
                        home_totals[2.5] = odds
        
        # Total 2 (ID "62") - Équipe extérieur  
        if "62" in markets:
            market = markets["62"]
            for outcome in market.get("outcomes", []):
                name = outcome.get("name", "").lower()
                odds = outcome.get("odds")
                
                if "over" in name and odds and odds >= self.min_odds_threshold:
                    if "1.5" in name:
                        away_totals[1.5] = odds
                    elif "2.5" in name:
                        away_totals[2.5] = odds
        
        return home_totals, away_totals
    
    def extract_total_goals(self, markets):
        """Extrait les totaux de buts du match."""
        total_goals = {"over": {}, "under": {}}
        
        # Total (ID "17")
        if "17" in markets:
            market = markets["17"]
            
            for outcome in market.get("outcomes", []):
                name = outcome.get("name", "").lower()
                odds = outcome.get("odds")
                
                if odds and odds >= self.min_odds_threshold:
                    if "over" in name:
                        if "1.5" in name:
                            total_goals["over"][1.5] = odds
                        elif "2.5" in name:
                            total_goals["over"][2.5] = odds
                        elif "3.5" in name:
                            total_goals["over"][3.5] = odds
                    elif "under" in name:
                        if "1.5" in name:
                            total_goals["under"][1.5] = odds
                        elif "2.5" in name:
                            total_goals["under"][2.5] = odds
                        elif "3.5" in name:
                            total_goals["under"][3.5] = odds
        
        return total_goals
    
    def get_1x2_and_handicap_odds(self, markets):
        """Récupère les cotes 1X2 et Handicap -1."""
        result_odds = {"home": None, "draw": None, "away": None}
        handicap_odds = {"home_minus1": None, "away_minus1": None}
        
        # 1X2 (ID "1")
        if "1" in markets:
            market = markets["1"]
            for outcome in market.get("outcomes", []):
                name = outcome.get("name", "").lower()
                odds = outcome.get("odds")
                
                if odds and odds >= self.min_odds_threshold:
                    if "home" in name:
                        result_odds["home"] = odds
                    elif "draw" in name:
                        result_odds["draw"] = odds  
                    elif "away" in name:
                        result_odds["away"] = odds
        
        # Handicap (ID "2")
        if "2" in markets:
            market = markets["2"]
            for outcome in market.get("outcomes", []):
                name = outcome.get("name", "").lower()
                odds = outcome.get("odds")
                
                if odds and odds >= self.min_odds_threshold:
                    if "home" in name and "-1" in name and "1.5" not in name:
                        handicap_odds["home_minus1"] = odds
                    elif "away" in name and "-1" in name and "1.5" not in name:
                        handicap_odds["away_minus1"] = odds
        
        return result_odds, handicap_odds
    
    def get_btts_odds(self, markets):
        """Récupère les cotes Both Teams To Score."""
        btts_odds = {"yes": None, "no": None}
        
        # Both Teams To Score (ID "19")
        if "19" in markets:
            market = markets["19"]
            for outcome in market.get("outcomes", []):
                name = outcome.get("name", "").lower() 
                odds = outcome.get("odds")
                
                if odds and odds >= self.min_odds_threshold:
                    if "yes" in name:
                        btts_odds["yes"] = odds
                    elif "no" in name:
                        btts_odds["no"] = odds
        
        return btts_odds
    
    def get_double_chance_odds(self, markets):
        """Récupère les cotes Double Chance."""
        double_chance_odds = {"1x": None, "x2": None, "12": None}
        
        # Double Chance (ID "8")
        if "8" in markets:
            market = markets["8"]
            for outcome in market.get("outcomes", []):
                name = outcome.get("name", "").lower()
                odds = outcome.get("odds")
                
                if odds and odds >= self.min_odds_threshold:
                    if "home or x" in name:
                        double_chance_odds["1x"] = odds
                    elif "away or x" in name:
                        double_chance_odds["x2"] = odds
                    elif "home or away" in name:
                        double_chance_odds["12"] = odds
        
        return double_chance_odds

    # ============= MODÈLES DE CALCUL AVEC RÈGLES CLARIFIÉES =============
    
    def calculate_all_predictions(self, total_goals, home_totals, away_totals, result_odds, handicap_odds, btts_odds, double_chance_odds, league_name):
        """Calcule les prédictions selon vos règles exactes clarifiées."""
        predictions = []
        
        # Récupérer les données de base
        home_over_15 = home_totals.get(1.5)
        away_over_15 = away_totals.get(1.5)
        home_win_odds = result_odds.get("home")
        away_win_odds = result_odds.get("away")
        home_handicap_minus1 = handicap_odds.get("home_minus1")
        away_handicap_minus1 = handicap_odds.get("away_minus1")
        
        # Variables de contrôle basées sur le barème
        home_respects_bareme = home_over_15 and home_over_15 <= self.max_odds_by_goals[1.5]
        away_respects_bareme = away_over_15 and away_over_15 <= self.max_odds_by_goals[1.5]
        
        logger.info(f"  Home Over 1.5: {home_over_15} ({'✅' if home_respects_bareme else '❌'})")
        logger.info(f"  Away Over 1.5: {away_over_15} ({'✅' if away_respects_bareme else '❌'})")
        
        # MODÈLE 1: +2,5 BUTS ET LES DEUX MARQUENT (si home 1.5 ET away 1.5 respectent le barème)
        if home_respects_bareme and away_respects_bareme:
            # Les deux équipes marquent
            if btts_odds["yes"] and btts_odds["yes"] >= self.min_odds_threshold:
                predictions.append({
                    "type": "Les deux équipes marquent",
                    "odds": btts_odds["yes"],
                    "confidence": 85,
                    "priority": 1,
                    "model": "Modèle 1: Home 1.5 ET Away 1.5 respectent barème"
                })
            
            # +2,5 buts
            over_25_real = total_goals["over"].get(2.5)
            if over_25_real and over_25_real <= self.max_odds_by_goals[2.5] and over_25_real >= self.min_odds_threshold:
                predictions.append({
                    "type": "+2,5 buts",
                    "odds": over_25_real,
                    "confidence": 80,
                    "priority": 1,
                    "model": "Modèle 1: Home 1.5 ET Away 1.5 respectent barème"
                })
        
        # MODÈLE 2: VICTOIRE DIRECTE OU DOUBLE CHANCE (formule handicap)
        if home_win_odds and home_handicap_minus1:
            ecart_home = round(home_handicap_minus1 - home_win_odds, 2)
            if 0.30 <= ecart_home <= 0.60:
                if home_win_odds < 2.0 and home_win_odds >= self.min_odds_threshold:
                    # Victoire directe si < 2.0
                    predictions.append({
                        "type": "Victoire domicile",
                        "odds": home_win_odds,
                        "confidence": 90,
                        "priority": 1,
                        "model": f"Modèle 2: Écart {ecart_home}, Cote < 2.0"
                    })
                elif home_win_odds >= 2.0:
                    # Double Chance si ≥ 2.0
                    dc_1x_odds = double_chance_odds.get("1x")
                    if dc_1x_odds and dc_1x_odds >= self.min_odds_threshold:
                        predictions.append({
                            "type": "Double chance 1X",
                            "odds": dc_1x_odds,
                            "confidence": 85,
                            "priority": 1,
                            "model": f"Modèle 2: Écart {ecart_home}, Cote ≥ 2.0 → Double Chance"
                        })
        
        if away_win_odds and away_handicap_minus1:
            ecart_away = round(away_handicap_minus1 - away_win_odds, 2)
            if 0.30 <= ecart_away <= 0.60:
                if away_win_odds < 2.0 and away_win_odds >= self.min_odds_threshold:
                    # Victoire directe si < 2.0
                    predictions.append({
                        "type": "Victoire extérieur",
                        "odds": away_win_odds,
                        "confidence": 88,
                        "priority": 1,
                        "model": f"Modèle 2: Écart {ecart_away}, Cote < 2.0"
                    })
                elif away_win_odds >= 2.0:
                    # Double Chance si ≥ 2.0
                    dc_x2_odds = double_chance_odds.get("x2")
                    if dc_x2_odds and dc_x2_odds >= self.min_odds_threshold:
                        predictions.append({
                            "type": "Double chance X2",
                            "odds": dc_x2_odds,
                            "confidence": 83,
                            "priority": 1,
                            "model": f"Modèle 2: Écart {ecart_away}, Cote ≥ 2.0 → Double Chance"
                        })
        
        # MODÈLE 3: -3,5 BUTS (aucune équipe ne respecte le barème)
        if not home_respects_bareme and not away_respects_bareme:
            under_35_real = total_goals["under"].get(3.5)
            
            # CORRECTION: Cote max 3.00 pour -3,5 buts
            if under_35_real and under_35_real <= self.max_odds_by_goals[3.5] and under_35_real >= self.min_odds_threshold:
                predictions.append({
                    "type": "-3,5 buts",
                    "odds": under_35_real,
                    "confidence": 75,
                    "priority": 2,
                    "model": "Modèle 3: Aucune équipe ne respecte barème"
                })
        
        # MODÈLE 4: DOUBLE CHANCE (une seule équipe respecte le barème)
        if home_respects_bareme and not away_respects_bareme:
            dc_1x_odds = double_chance_odds.get("1x")
            if dc_1x_odds and dc_1x_odds >= self.min_odds_threshold:
                predictions.append({
                    "type": "Double chance 1X",
                    "odds": dc_1x_odds,
                    "confidence": 78,
                    "priority": 2,
                    "model": "Modèle 4: Seule équipe domicile respecte barème"
                })
        
        if away_respects_bareme and not home_respects_bareme:
            dc_x2_odds = double_chance_odds.get("x2")
            if dc_x2_odds and dc_x2_odds >= self.min_odds_threshold:
                predictions.append({
                    "type": "Double chance X2",
                    "odds": dc_x2_odds,
                    "confidence": 76,
                    "priority": 2,
                    "model": "Modèle 4: Seule équipe extérieur respecte barème"
                })
        
        # MODÈLE 5: +1,5 BUTS (une seule équipe respecte le barème)
        if (home_respects_bareme and not away_respects_bareme) or (away_respects_bareme and not home_respects_bareme):
            over_15_real = total_goals["over"].get(1.5)
            if over_15_real and over_15_real <= self.max_odds_by_goals[1.5] and over_15_real >= self.min_odds_threshold:
                predictions.append({
                    "type": "+1,5 buts",
                    "odds": over_15_real,
                    "confidence": 82,
                    "priority": 2,
                    "model": "Modèle 5: Une seule équipe respecte barème"
                })
        
        return predictions
    
    def select_best_prediction(self, predictions):
        """Sélectionne la meilleure prédiction pour le match."""
        if not predictions:
            return None
        
        # Filtrer les prédictions avec cote >= 1.10
        valid_predictions = [p for p in predictions if p["odds"] >= self.min_odds_threshold]
        
        if not valid_predictions:
            return None
        
        # Trier par priorité, puis par confiance, puis par cote
        valid_predictions.sort(key=lambda x: (x["priority"], -x["confidence"], x["odds"]))
        
        return valid_predictions[0]
    
    def generate_predictions(self):
        """Génère les meilleures prédictions pour les matchs sélectionnés."""
        logger.info("=== GÉNÉRATION DES PRÉDICTIONS FINALES ===")
        
        used_prediction_types = []
        
        for match in self.selected_matches:
            match_id = match.get("id")
            home_team = match.get("home_team", "Équipe domicile")
            away_team = match.get("away_team", "Équipe extérieur")
            league_name = match.get("league", "Ligue inconnue")
            
            if not self.is_valid_team_name(home_team) or not self.is_valid_team_name(away_team):
                logger.warning(f"Match ignoré - noms d'équipes invalides: {home_team} vs {away_team}")
                continue
                
            logger.info(f"Analyse du match {home_team} vs {away_team} (ID: {match_id})...")
            
            # Récupérer les cotes pour ce match
            markets = self.get_match_odds(match_id)
            
            if not markets:
                logger.warning(f"Pas de cotes disponibles pour {home_team} vs {away_team}, match ignoré")
                continue
            
            # Extraire toutes les données
            total_goals = self.extract_total_goals(markets)
            home_totals, away_totals = self.extract_team_totals(markets)
            result_odds, handicap_odds = self.get_1x2_and_handicap_odds(markets)
            btts_odds = self.get_btts_odds(markets)
            double_chance_odds = self.get_double_chance_odds(markets)
            
            logger.info(f"  Données extraites - Over: {len(total_goals['over'])}, Home: {len(home_totals)}, Away: {len(away_totals)}")
            
            # Générer toutes les prédictions possibles
            all_predictions = self.calculate_all_predictions(
                total_goals, home_totals, away_totals, result_odds, handicap_odds, btts_odds, double_chance_odds, league_name
            )
            
            logger.info(f"  Prédictions générées: {len(all_predictions)}")
            
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
                    if "-" in prediction_type:
                        selected_prediction = prediction
                        break
            
            # Si toujours pas de prédiction, prendre la prédiction de plus haute confiance
            # même si elle est déjà utilisée
            if not selected_prediction and all_predictions:
                selected_prediction = all_predictions[0]
                
            # Si une prédiction a été trouvée
            if selected_prediction:
                # Vérifier une dernière fois que la cote est >= 1.10
                if selected_prediction["odds"] >= self.min_odds_threshold:
                    # Ajouter les informations du match
                    selected_prediction["match_id"] = match_id
                    selected_prediction["home_team"] = home_team
                    selected_prediction["away_team"] = away_team
                    selected_prediction["league_name"] = league_name
                    selected_prediction["start_timestamp"] = match.get("start_timestamp", 0)
                    
                    # Stocker la prédiction
                    self.predictions[match_id] = selected_prediction
                    
                    logger.info(f"  ✅ Prédiction: {selected_prediction['type']} (Cote: {selected_prediction['odds']}, Confiance: {selected_prediction['confidence']:.1f}%)")
                    if "model" in selected_prediction:
                        logger.info(f"      Modèle: {selected_prediction['model']}")
                else:
                    logger.warning(f"Prédiction rejetée - cote trop faible: {selected_prediction['odds']} < {self.min_odds_threshold}")
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
        logger.info("=== RÉCAPITULATIF DU COUPON FINAL ===")
        logger.info("=" * 80)
        
        for i, (match_id, pred) in enumerate(self.predictions.items()):
            # Calculer l'heure du match au format local
            start_time = datetime.fromtimestamp(pred["start_timestamp"], self.timezone).strftime("%H:%M")
            
            logger.info(f"MATCH {i+1}: {pred['home_team']} vs {pred['away_team']}")
            logger.info(f"Ligue: {pred['league_name']}")
            logger.info(f"Heure: {start_time}")
            logger.info(f"Prédiction: {pred['type']}")
            logger.info(f"Cote: {pred['odds']} (≥ {self.min_odds_threshold} ✅)")
            logger.info(f"Confiance: {pred['confidence']:.1f}%")
            if "model" in pred:
                logger.info(f"Modèle: {pred['model']}")
            logger.info("-" * 50)
        
        logger.info(f"COTE TOTALE DU COUPON: {self.coupon_total_odds}")
        logger.info("=" * 80 + "\n")
    
    def format_prediction_message(self):
    """Formate le message de prédiction pour Telegram avec mise en forme française améliorée."""
    now = datetime.now(self.timezone)
    date_str = now.strftime("%d/%m/%Y")
    
    # Titre en gras avec émojis
    message = "🎯 **COUPON DU JOUR** 🎯\n"
    message += f"📅 **{date_str}**\n\n"
    
    # Si aucune prédiction n'a été générée
    if not self.predictions:
        message += "_Aucune prédiction fiable n'a pu être générée pour aujourd'hui. Revenez demain !_"
        return message
    
    # Ajouter chaque prédiction au message
    for i, (match_id, pred) in enumerate(self.predictions.items()):
        # Séparateur
        if i > 0:
            message += "----------------------------\n\n"
        
        # Calculer l'heure du match au format local
        start_time = datetime.fromtimestamp(pred["start_timestamp"], self.timezone).strftime("%H:%M")
        
        # Nom de la ligue en MAJUSCULES et gras avec italique
        message += f"🏆 ***{pred['league_name'].upper()}***\n"
        
        # Équipes en gras et italique
        message += f"⚽️ ***{pred['home_team']} vs {pred['away_team']}***\n"
        
        # Heure en italique uniquement
        message += f"⏰ _HEURE : {start_time}_\n"
        
        # Prédiction en gras et italique
        message += f"🎯 ***PRÉDICTION: {pred['type']}***\n"
        
        # Cote en gras et italique
        message += f"💰 ***Cote: {pred['odds']}***\n"
    
    # Ajouter la cote totale en gras et italique
    message += f"----------------------------\n\n"
    message += f"📊 ***COTE TOTALE: {self.coupon_total_odds}***\n"
    message += f"📈 ***{len(self.predictions)} MATCHS SÉLECTIONNÉS***\n\n"
    
    # Conseils en italique uniquement
    message += f"_💡 Prédictions basées sur notre barème de sécurité_\n"
    message += f"_🎲 Misez toujours 5% de votre capital maximum_\n"
    message += f"_🔞 Pariez de façon responsable._"
    
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
        
        logger.info("Envoi des prédictions finales sur Telegram...")
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
