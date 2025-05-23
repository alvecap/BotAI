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
        
        # NOUVEAU BARÈME : Paramètres des prédictions basés sur votre barème
        self.max_odds_by_goals = {
            0.5: 1.60,   # Over 0.5
            1.5: 1.99,   # Over 1.5  
            2.5: 2.50,   # Over 2.5
            3.5: 3.80,   # Over 3.5
            4.5: 5.50,   # Over 4.5
            5.5: 7.00    # Over 5.5
        }
        
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
            # Sélectionner des matchs pour les prédictions (maintenant 6 matchs)
            self.select_matches(all_matches)
            
            # Générer des prédictions avec les nouveaux modèles
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
        """Sélectionne 6 matchs pour les prédictions avec priorité aux ligues à faible scoring."""
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
        
        # Augmenter à 6 matchs maximum
        max_matches = min(6, len(all_matches))
        
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

    # ============= NOUVELLES FONCTIONS D'EXTRACTION BASÉES SUR LE BARÈME =============
    
    def extract_team_totals(self, markets):
        """Extrait les totaux individuels des équipes avec le nouveau format."""
        home_totals = {}
        away_totals = {}
        
        # Total 1 (ID "15") - Équipe domicile
        if "15" in markets:
            market = markets["15"]
            for outcome in market.get("outcomes", []):
                name = outcome.get("name", "").lower()
                odds = outcome.get("odds")
                
                if "over" in name and odds:
                    if "0.5" in name:
                        home_totals[0.5] = odds
                    elif "1.5" in name:
                        home_totals[1.5] = odds
                    elif "2.5" in name:
                        home_totals[2.5] = odds
        
        # Total 2 (ID "62") - Équipe extérieur  
        if "62" in markets:
            market = markets["62"]
            for outcome in market.get("outcomes", []):
                name = outcome.get("name", "").lower()
                odds = outcome.get("odds")
                
                if "over" in name and odds:
                    if "0.5" in name:
                        away_totals[0.5] = odds
                    elif "1.5" in name:
                        away_totals[1.5] = odds
                    elif "2.5" in name:
                        away_totals[2.5] = odds
        
        return home_totals, away_totals
    
    def extract_total_goals(self, markets):
        """Extrait les totaux de buts du match avec le nouveau format."""
        total_goals = {"over": {}, "under": {}}
        
        # Total (ID "17")
        if "17" in markets:
            market = markets["17"]
            
            for outcome in market.get("outcomes", []):
                name = outcome.get("name", "").lower()
                odds = outcome.get("odds")
                
                if odds:
                    if "over" in name:
                        if "0.5" in name:
                            total_goals["over"][0.5] = odds
                        elif "1.5" in name:
                            total_goals["over"][1.5] = odds
                        elif "2.5" in name:
                            total_goals["over"][2.5] = odds
                        elif "3.5" in name:
                            total_goals["over"][3.5] = odds
                        elif "4.5" in name:
                            total_goals["over"][4.5] = odds
                        elif "5.5" in name:
                            total_goals["over"][5.5] = odds
                    elif "under" in name:
                        if "0.5" in name:
                            total_goals["under"][0.5] = odds
                        elif "1.5" in name:
                            total_goals["under"][1.5] = odds
                        elif "2.5" in name:
                            total_goals["under"][2.5] = odds
                        elif "3.5" in name:
                            total_goals["under"][3.5] = odds
                        elif "4.5" in name:
                            total_goals["under"][4.5] = odds
                        elif "5.5" in name:
                            total_goals["under"][5.5] = odds
        
        return total_goals
    
    def get_1x2_and_handicap_odds(self, markets):
        """Récupère les cotes 1X2 et Handicap -1 avec le nouveau format."""
        result_odds = {"home": None, "draw": None, "away": None}
        handicap_odds = {"home_minus1": None, "away_minus1": None}
        
        # 1X2 (ID "1")
        if "1" in markets:
            market = markets["1"]
            for outcome in market.get("outcomes", []):
                name = outcome.get("name", "").lower()
                odds = outcome.get("odds")
                
                if "home" in name and odds:
                    result_odds["home"] = odds
                elif "draw" in name and odds:
                    result_odds["draw"] = odds  
                elif "away" in name and odds:
                    result_odds["away"] = odds
        
        # Handicap (ID "2")
        if "2" in markets:
            market = markets["2"]
            for outcome in market.get("outcomes", []):
                name = outcome.get("name", "").lower()
                odds = outcome.get("odds")
                
                if "home" in name and "-1" in name and "1.5" not in name and odds:
                    handicap_odds["home_minus1"] = odds
                elif "away" in name and "-1" in name and "1.5" not in name and odds:
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
                
                if "yes" in name and odds:
                    btts_odds["yes"] = odds
                elif "no" in name and odds:
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
                
                if "home or x" in name or "1x" in name.replace(" ", "") and odds:
                    double_chance_odds["1x"] = odds
                elif "away or x" in name or "x2" in name.replace(" ", "") or "2x" in name.replace(" ", "") and odds:
                    double_chance_odds["x2"] = odds
                elif "home or away" in name or "12" in name.replace(" ", "") and odds:
                    double_chance_odds["12"] = odds
        
        return double_chance_odds

    # ============= NOUVEAUX MODÈLES DE CALCUL BASÉS SUR LE BARÈME =============
    
    def calculate_all_predictions(self, total_goals, home_totals, away_totals, result_odds, handicap_odds, btts_odds, double_chance_odds, league_name):
        """Calcule TOUTES les prédictions possibles selon vos modèles basés sur le barème."""
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
        
        # MODÈLE 1: LES DEUX ÉQUIPES MARQUENT + OVER 2.5 (les deux respectent le barème)
        if home_respects_bareme and away_respects_bareme:
            # BTTS avec cote réelle si disponible
            if btts_odds["yes"]:
                predictions.append({
                    "type": "Les deux équipes marquent",
                    "odds": btts_odds["yes"],
                    "confidence": 85,
                    "priority": 1,
                    "model": "Barème: Les 2 équipes respectent Over 1.5"
                })
            
            # Over 2.5 buts
            over_25_real = total_goals["over"].get(2.5)
            if over_25_real and over_25_real <= self.max_odds_by_goals[2.5]:
                predictions.append({
                    "type": "Over 2.5 buts",
                    "odds": over_25_real,
                    "confidence": 80,
                    "priority": 1,
                    "model": "Barème: Les 2 équipes respectent Over 1.5"
                })
        
        # MODÈLE 2: VICTOIRE DIRECTE OU DOUBLE CHANCE (formule handicap + nouvelle logique)
        if home_win_odds and home_handicap_minus1:
            ecart_home = round(home_handicap_minus1 - home_win_odds, 2)
            if 0.30 <= ecart_home <= 0.60:
                # Nouvelle logique : Victoire directe si < 2.0, sinon Double Chance 1X
                if home_win_odds < 2.0:
                    predictions.append({
                        "type": "Victoire domicile",
                        "odds": home_win_odds,
                        "confidence": 90,
                        "priority": 1,
                        "model": f"Handicap: Écart {ecart_home}, Cote < 2.0"
                    })
                else:
                    # Cote ≥ 2.0 → Double Chance 1X
                    dc_1x_odds = double_chance_odds.get("1x")
                    if dc_1x_odds:
                        predictions.append({
                            "type": "Double chance 1X",
                            "odds": dc_1x_odds,
                            "confidence": 85,
                            "priority": 1,
                            "model": f"Handicap: Écart {ecart_home}, Cote ≥ 2.0"
                        })
        
        if away_win_odds and away_handicap_minus1:
            ecart_away = round(away_handicap_minus1 - away_win_odds, 2)
            if 0.30 <= ecart_away <= 0.60:
                # Nouvelle logique : Victoire directe si < 2.0, sinon Double Chance X2
                if away_win_odds < 2.0:
                    predictions.append({
                        "type": "Victoire extérieur",
                        "odds": away_win_odds,
                        "confidence": 88,
                        "priority": 1,
                        "model": f"Handicap: Écart {ecart_away}, Cote < 2.0"
                    })
                else:
                    # Cote ≥ 2.0 → Double Chance X2
                    dc_x2_odds = double_chance_odds.get("x2")
                    if dc_x2_odds:
                        predictions.append({
                            "type": "Double chance X2",
                            "odds": dc_x2_odds,
                            "confidence": 83,
                            "priority": 1,
                            "model": f"Handicap: Écart {ecart_away}, Cote ≥ 2.0"
                        })
        
        # MODÈLE 3: UNDER 3.5 BUTS (aucune équipe ne respecte le barème)
        if not home_respects_bareme and not away_respects_bareme:
            # Utiliser directement la cote Under 3.5 de l'API
            under_35_real = total_goals["under"].get(3.5)
            
            if under_35_real and under_35_real <= 3.80:  # Respecte notre barème théorique
                predictions.append({
                    "type": "Under 3.5 buts",
                    "odds": under_35_real,
                    "confidence": 75,
                    "priority": 2,
                    "model": "Barème: Aucune équipe ne respecte Over 1.5"
                })
        
        # MODÈLE 4: DOUBLE CHANCE (une seule équipe respecte le barème)
        if home_respects_bareme and not away_respects_bareme:
            dc_1x_odds = double_chance_odds.get("1x")
            if dc_1x_odds:
                predictions.append({
                    "type": "Double chance 1X",
                    "odds": dc_1x_odds,
                    "confidence": 78,
                    "priority": 2,
                    "model": "Barème: Seule équipe domicile respecte Over 1.5"
                })
        
        if away_respects_bareme and not home_respects_bareme:
            dc_x2_odds = double_chance_odds.get("x2")
            if dc_x2_odds:
                predictions.append({
                    "type": "Double chance X2",
                    "odds": dc_x2_odds,
                    "confidence": 76,
                    "priority": 2,
                    "model": "Barème: Seule équipe extérieur respecte Over 1.5"
                })
        
        # MODÈLE 5: OVER 1.5 BUTS (une seule équipe respecte le barème)
        if (home_respects_bareme and not away_respects_bareme) or (away_respects_bareme and not home_respects_bareme):
            over_15_real = total_goals["over"].get(1.5)
            if over_15_real and over_15_real <= self.max_odds_by_goals[1.5]:
                predictions.append({
                    "type": "Over 1.5 buts",
                    "odds": over_15_real,
                    "confidence": 82,
                    "priority": 2,
                    "model": "Barème: Une seule équipe respecte Over 1.5"
                })
        
        # PRÉDICTIONS SUPPLÉMENTAIRES basées sur le barème direct
        for goal_line, max_allowed_odds in self.max_odds_by_goals.items():
            if goal_line in total_goals["over"]:
                actual_odds = total_goals["over"][goal_line]
                if actual_odds <= max_allowed_odds:
                    predictions.append({
                        "type": f"Over {goal_line} buts",
                        "odds": actual_odds,
                        "confidence": round((max_allowed_odds - actual_odds) / max_allowed_odds * 100, 1),
                        "priority": 3,
                        "model": f"Barème direct: {actual_odds} ≤ {max_allowed_odds}"
                    })
        
        # Ajustement selon le profil de la ligue
        for prediction in predictions:
            prediction["confidence"] = self.adjust_confidence_by_league(prediction, league_name)
        
        return predictions
    
    def adjust_confidence_by_league(self, prediction, league_name):
        """Ajuste la confiance selon le type de ligue."""
        base_confidence = prediction["confidence"]
        prediction_type = prediction["type"]
        league_profile = self.get_league_scoring_profile(league_name)
        
        # Ajustements selon le profil de la ligue
        if league_profile == "low":
            # Les ligues à faible scoring favorisent les "under" et "double chance"
            if "under" in prediction_type.lower() or "double chance" in prediction_type.lower():
                return min(95, base_confidence * 1.1)
            elif "over" in prediction_type.lower() and "marquent" in prediction_type.lower():
                return max(60, base_confidence * 0.9)
        
        elif league_profile == "high":
            # Les ligues à fort scoring favorisent les "over" et "btts"
            if "over" in prediction_type.lower() or "marquent" in prediction_type.lower():
                return min(95, base_confidence * 1.1)
            elif "under" in prediction_type.lower():
                return max(60, base_confidence * 0.9)
        
        return base_confidence
    
    def select_best_prediction(self, predictions):
        """Sélectionne la meilleure prédiction pour le match."""
        if not predictions:
            return None
        
        # Trier par priorité, puis par confiance, puis par cote
        predictions.sort(key=lambda x: (x["priority"], -x["confidence"], x["odds"]))
        
        return predictions[0]
    
    def generate_match_predictions(self, match_id, markets, league_name, home_team, away_team):
        """
        Génère toutes les prédictions possibles pour un match spécifique avec les nouveaux modèles.
        """
        # Extraire toutes les données avec le nouveau format
        total_goals = self.extract_total_goals(markets)
        home_totals, away_totals = self.extract_team_totals(markets)
        result_odds, handicap_odds = self.get_1x2_and_handicap_odds(markets)
        btts_odds = self.get_btts_odds(markets)
        double_chance_odds = self.get_double_chance_odds(markets)
        
        logger.info(f"  Données extraites - Over: {len(total_goals['over'])}, Home: {len(home_totals)}, Away: {len(away_totals)}")
        
        # Calculer toutes les prédictions possibles avec les nouveaux modèles
        all_predictions = self.calculate_all_predictions(
            total_goals, home_totals, away_totals, result_odds, handicap_odds, btts_odds, double_chance_odds, league_name
        )
        
        logger.info(f"  Prédictions générées: {len(all_predictions)}")
        
        return all_predictions
    
    def generate_predictions(self):
        """
        Génère les meilleures prédictions pour les matchs sélectionnés 
        en utilisant les nouveaux modèles basés sur le barème.
        """
        logger.info("=== GÉNÉRATION DES PRÉDICTIONS AVEC NOUVEAUX MODÈLES ===")
        
        # Liste des types de prédictions déjà utilisés pour éviter les doublons
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
            
            # Générer toutes les prédictions possibles pour ce match avec les nouveaux modèles
            all_predictions = self.generate_match_predictions(match_id, markets, league_name, home_team, away_team)
            
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
                    if "under" in prediction_type.lower():
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
                
                logger.info(f"  ✅ Prédiction: {selected_prediction['type']} (Cote: {selected_prediction['odds']}, Confiance: {selected_prediction['confidence']:.1f}%)")
                if "model" in selected_prediction:
                    logger.info(f"      Modèle: {selected_prediction['model']}")
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
        logger.info("=== RÉCAPITULATIF DU COUPON BASÉ SUR LE BARÈME ===")
        logger.info("=" * 80)
        
        for i, (match_id, pred) in enumerate(self.predictions.items()):
            # Calculer l'heure du match au format local
            start_time = datetime.fromtimestamp(pred["start_timestamp"], self.timezone).strftime("%H:%M")
            
            logger.info(f"MATCH {i+1}: {pred['home_team']} vs {pred['away_team']}")
            logger.info(f"Ligue: {pred['league_name']}")
            logger.info(f"Heure: {start_time}")
            logger.info(f"Prédiction: {pred['type']}")
            logger.info(f"Cote: {pred['odds']}")
            logger.info(f"Confiance: {pred['confidence']:.1f}%")
            if "model" in pred:
                logger.info(f"Modèle: {pred['model']}")
            logger.info("-" * 50)
        
        logger.info(f"COTE TOTALE DU COUPON: {self.coupon_total_odds}")
        logger.info("=" * 80 + "\n")
    
    def format_prediction_message(self):
        """Formate le message de prédiction pour Telegram avec mise en forme Markdown améliorée."""
        now = datetime.now(self.timezone)
        date_str = now.strftime("%d/%m/%Y")
        
        # Titre en gras avec émojis
        message = "🎯 *COUPON BASÉ SUR LE BARÈME* 🎯\n"
        message += f"📅 *{date_str}*\n\n"
        
        # Si aucune prédiction n'a été générée
        if not self.predictions:
            message += "_Aucune prédiction fiable n'a pu être générée pour aujourd'hui selon le barème. Revenez demain!_"
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
            
            # Cote et confiance
            message += f"💰 Cote: {pred['odds']} | 📊 Confiance: {pred['confidence']:.0f}%\n"
        
        # Ajouter la cote totale en gras
        message += f"----------------------------\n\n"
        message += f"📊 *COTE TOTALE: {self.coupon_total_odds}*\n"
        message += f"📈 *{len(self.predictions)} MATCHS SÉLECTIONNÉS*\n\n"
        
        # Conseils en italique
        message += f"💡 _Prédictions basées sur notre barème de sécurité_\n"
        message += f"🎲 _Misez toujours 5% de votre capital maximum_\n"
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
        
        logger.info("Envoi des prédictions basées sur le barème sur Telegram...")
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
