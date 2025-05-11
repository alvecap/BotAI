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
import statistics

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

    def analyze_1x2_market(self, markets, home_team, away_team):
        """Analyse le marché 1X2 pour déterminer les prédictions possibles."""
        if "1" not in markets:  # 1 = 1X2
            return []
        
        predictions = []
        
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
            return predictions
        
        # Calculer la probabilité implicite (sans la marge du bookmaker)
        total_prob = 1/home_odds + 1/away_odds + 1/draw_odds
        home_prob = (1/home_odds) / total_prob
        away_prob = (1/away_odds) / total_prob
        draw_prob = (1/draw_odds) / total_prob
        
        # Seuils de confiance pour différentes prédictions
        home_threshold = 0.48  # Probabilité pour parier sur victoire domicile
        away_threshold = 0.48  # Probabilité pour parier sur victoire extérieur
        low_draw_threshold = 0.24  # Probabilité basse pour un match nul
        
        # Vérifier si une équipe est fortement favorite
        if home_prob > home_threshold:
            predictions.append({
                "type": f"{home_team} gagne",
                "odds": home_odds,
                "confidence": home_prob,
                "market": "1X2"
            })
        
        if away_prob > away_threshold:
            predictions.append({
                "type": f"{away_team} gagne",
                "odds": away_odds,
                "confidence": away_prob,
                "market": "1X2"
            })
        
        # Proposer une double chance si le match semble déséquilibré
        if home_prob > 0.38 and draw_prob > 0.25:
            predictions.append({
                "type": "1X",
                "odds": round(1 / (home_prob + draw_prob), 2),
                "confidence": home_prob + draw_prob,
                "market": "Double Chance"
            })
        
        if away_prob > 0.38 and draw_prob > 0.25:
            predictions.append({
                "type": "X2",
                "odds": round(1 / (away_prob + draw_prob), 2),
                "confidence": away_prob + draw_prob,
                "market": "Double Chance"
            })
        
        # Si le match nul a une faible probabilité, suggérer 12
        if draw_prob < low_draw_threshold:
            predictions.append({
                "type": "12",
                "odds": round(1 / (home_prob + away_prob), 2),
                "confidence": home_prob + away_prob,
                "market": "Double Chance"
            })
        
        return predictions

    def analyze_btts_market(self, markets):
        """Analyse le marché 'Les deux équipes marquent' (Both Teams To Score)."""
        predictions = []
        
        # Trouver le marché BTTS
        btts_yes_odds = btts_no_odds = None
        
        for market_id, market in markets.items():
            if "both teams to score" in market.get("name", "").lower():
                for outcome in market.get("outcomes", []):
                    if outcome.get("name", "").lower() in ["yes", "oui"]:
                        btts_yes_odds = outcome.get("odds")
                    elif outcome.get("name", "").lower() in ["no", "non"]:
                        btts_no_odds = outcome.get("odds")
        
        if not btts_yes_odds or not btts_no_odds:
            return predictions
        
        # Calculer les probabilités implicites
        total_prob = 1/btts_yes_odds + 1/btts_no_odds
        yes_prob = (1/btts_yes_odds) / total_prob
        no_prob = (1/btts_no_odds) / total_prob
        
        # Vérifier si les cotes suggèrent clairement que les deux équipes vont marquer
        if yes_prob > 0.58:
            predictions.append({
                "type": "Les 2 équipes marquent",
                "odds": btts_yes_odds,
                "confidence": yes_prob,
                "market": "BTTS"
            })
        
        # Ou si elles suggèrent qu'une seule équipe marquera
        if no_prob > 0.58:
            predictions.append({
                "type": "Une seule/aucune équipe marque",
                "odds": btts_no_odds,
                "confidence": no_prob,
                "market": "BTTS"
            })
        
        return predictions

    def analyze_over_under_markets(self, markets):
        """Analyse les marchés over/under pour les totaux de buts."""
        predictions = []
        
        # Capter les cotes pour différents totaux
        over_under_data = {}
        
        for market_id, market in markets.items():
            if "total" in market.get("name", "").lower() and not "team" in market.get("name", "").lower():
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    if "over" in name or "under" in name:
                        # Extraire le nombre de buts
                        parts = name.split()
                        for i, part in enumerate(parts):
                            if part in ["over", "under"]:
                                if i + 1 < len(parts) and parts[i+1].replace(".", "").isdigit():
                                    total = float(parts[i+1])
                                    direction = part
                                    
                                    if total not in over_under_data:
                                        over_under_data[total] = {}
                                    
                                    over_under_data[total][direction] = odds
        
        # Analyser les données collectées
        for total, odds in over_under_data.items():
            if "over" in odds and "under" in odds:
                # Calculer les probabilités implicites
                over_odds = odds["over"]
                under_odds = odds["under"]
                
                total_prob = 1/over_odds + 1/under_odds
                over_prob = (1/over_odds) / total_prob
                under_prob = (1/under_odds) / total_prob
                
                # Vérifier s'il y a une forte probabilité dans une direction
                if total == 2.5 and over_prob > 0.57:
                    predictions.append({
                        "type": f"+2.5 buts",
                        "odds": over_odds,
                        "confidence": over_prob,
                        "market": "Over/Under"
                    })
                elif total == 2.5 and under_prob > 0.57:
                    predictions.append({
                        "type": f"-2.5 buts",
                        "odds": under_odds,
                        "confidence": under_prob,
                        "market": "Over/Under"
                    })
                elif total == 3.5 and under_prob > 0.56:
                    predictions.append({
                        "type": f"-3.5 buts",
                        "odds": under_odds,
                        "confidence": under_prob,
                        "market": "Over/Under"
                    })
                elif total == 1.5 and over_prob > 0.65:
                    predictions.append({
                        "type": f"+1.5 buts",
                        "odds": over_odds,
                        "confidence": over_prob,
                        "market": "Over/Under"
                    })
        
        return predictions

    def analyze_exact_scores(self, markets):
        """Analyse les scores exacts pour déduire des tendances."""
        if "18" not in markets:  # 18 = Score exact
            return []
        
        predictions = []
        scores = []
        
        # Récupérer tous les scores et leurs cotes
        for outcome in markets["18"].get("outcomes", []):
            score_name = outcome.get("name", "")
            odds = outcome.get("odds")
            
            if "-" in score_name and odds:
                scores.append({"name": score_name, "odds": odds})
        
        if not scores:
            return predictions
        
        # Trier par cote croissante (les scores les plus probables d'abord)
        scores.sort(key=lambda x: x["odds"])
        
        # Analyser les 5 scores les plus probables
        top_scores = scores[:5]
        
        # Compter les buts totaux des scores les plus probables
        total_goals = []
        for score in top_scores:
            try:
                parts = score["name"].split("-")
                home_goals = int(parts[0])
                away_goals = int(parts[1])
                total = home_goals + away_goals
                total_goals.append(total)
            except:
                continue
        
        # Si les données sont suffisantes
        # Si les données sont suffisantes
        if total_goals:
            avg_goals = sum(total_goals) / len(total_goals)
            
            # Si la moyenne des buts dans les scores probables est faible
            if avg_goals < 2.2:
                # Suggérer un pari sur moins de buts
                predictions.append({
                    "type": "-2.5 buts",
                    "odds": None,  # À rechercher dans les marchés over/under
                    "confidence": 0.65,
                    "market": "Score Exact -> Over/Under"
                })
            elif avg_goals > 3.0:
                # Suggérer un pari sur plus de buts
                predictions.append({
                    "type": "+2.5 buts",
                    "odds": None,  # À rechercher dans les marchés over/under
                    "confidence": 0.65,
                    "market": "Score Exact -> Over/Under"
                })
            
            # Vérifier si les deux équipes marquent dans la majorité des scores probables
            btts_count = 0
            for score in top_scores:
                try:
                    parts = score["name"].split("-")
                    home_goals = int(parts[0])
                    away_goals = int(parts[1])
                    if home_goals > 0 and away_goals > 0:
                        btts_count += 1
                except:
                    continue
            
            if btts_count >= 3:  # Au moins 3 des 5 scores probables impliquent BTTS
                predictions.append({
                    "type": "Les 2 équipes marquent",
                    "odds": None,  # À rechercher dans le marché BTTS
                    "confidence": 0.6,
                    "market": "Score Exact -> BTTS"
                })
        
        return predictions

    def analyze_home_away_dominance(self, markets, home_team, away_team):
        """Analyse si une équipe est particulièrement dominante selon diverses statistiques."""
        predictions = []
        
        # Vérifier les cotes handicap
        handicap_advantage = None
        
        if "16" in markets:  # 16 = Handicap
            for outcome in markets["16"].get("outcomes", []):
                name = outcome.get("name", "")
                odds = outcome.get("odds")
                
                # Chercher un handicap -1 avec une cote raisonnable
                if "1 (-1)" in name and odds < 2.50:
                    handicap_advantage = "home"
                elif "2 (-1)" in name and odds < 2.50:
                    handicap_advantage = "away"
        
        # Vérifier les cotes de victoire à zéro
        win_to_nil_advantage = None
        
        for market_id, market in markets.items():
            if "win to nil" in market.get("name", "").lower():
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    odds = outcome.get("odds")
                    
                    if "1" in name and odds < 3.20:
                        win_to_nil_advantage = "home"
                    elif "2" in name and odds < 3.20:
                        win_to_nil_advantage = "away"
        
        # Si plusieurs indicateurs convergent vers la même équipe
        if handicap_advantage == "home" and win_to_nil_advantage == "home":
            predictions.append({
                "type": f"{home_team} gagne",
                "odds": None,  # À rechercher dans le marché 1X2
                "confidence": 0.70,
                "market": "Dominance Équipe"
            })
        elif handicap_advantage == "away" and win_to_nil_advantage == "away":
            predictions.append({
                "type": f"{away_team} gagne",
                "odds": None,  # À rechercher dans le marché 1X2
                "confidence": 0.70,
                "market": "Dominance Équipe"
            })
        
        return predictions

    def find_best_prediction(self, all_predictions, markets):
        """Trouve la meilleure prédiction parmi toutes les possibilités, en s'assurant d'avoir les cotes."""
        if not all_predictions:
            return None
        
        # Trier par niveau de confiance
        all_predictions.sort(key=lambda x: x["confidence"], reverse=True)
        
        # Vérifier et compléter les cotes manquantes
        for pred in all_predictions:
            if not pred["odds"]:
                if pred["type"] == "+2.5 buts":
                    for market_id, market in markets.items():
                        if "total" in market.get("name", "").lower():
                            for outcome in market.get("outcomes", []):
                                if "over 2.5" in outcome.get("name", "").lower():
                                    pred["odds"] = outcome.get("odds")
                
                elif pred["type"] == "-2.5 buts":
                    for market_id, market in markets.items():
                        if "total" in market.get("name", "").lower():
                            for outcome in market.get("outcomes", []):
                                if "under 2.5" in outcome.get("name", "").lower():
                                    pred["odds"] = outcome.get("odds")
                
                elif pred["type"] == "-3.5 buts":
                    for market_id, market in markets.items():
                        if "total" in market.get("name", "").lower():
                            for outcome in market.get("outcomes", []):
                                if "under 3.5" in outcome.get("name", "").lower():
                                    pred["odds"] = outcome.get("odds")
                
                elif pred["type"] == "+1.5 buts":
                    for market_id, market in markets.items():
                        if "total" in market.get("name", "").lower():
                            for outcome in market.get("outcomes", []):
                                if "over 1.5" in outcome.get("name", "").lower():
                                    pred["odds"] = outcome.get("odds")
                
                elif pred["type"] == "Les 2 équipes marquent":
                    for market_id, market in markets.items():
                        if "both teams to score" in market.get("name", "").lower():
                            for outcome in market.get("outcomes", []):
                                if outcome.get("name", "").lower() in ["yes", "oui"]:
                                    pred["odds"] = outcome.get("odds")
                
                elif "gagne" in pred["type"]:
                    team = pred["type"].split(" gagne")[0]
                    for outcome in markets.get("1", {}).get("outcomes", []):
                        if (outcome.get("name") == "1" and team == pred["home_team"]) or \
                           (outcome.get("name") == "2" and team == pred["away_team"]):
                            pred["odds"] = outcome.get("odds")
                
                elif pred["type"] in ["1X", "X2", "12"]:
                    for market_id, market in markets.items():
                        if "double chance" in market.get("name", "").lower():
                            for outcome in market.get("outcomes", []):
                                if outcome.get("name") == pred["type"]:
                                    pred["odds"] = outcome.get("odds")
        
        # Filtrer les prédictions sans cote
        valid_predictions = [p for p in all_predictions if p["odds"]]
        
        if not valid_predictions:
            # Fallback: créer une prédiction par défaut avec le marché 1X2
            if "1" in markets:
                # Trouver l'option avec la cote la plus basse (la plus probable)
                min_odds = float('inf')
                best_outcome = None
                
                for outcome in markets["1"].get("outcomes", []):
                    odds = outcome.get("odds")
                    if odds and odds < min_odds:
                        min_odds = odds
                        best_outcome = outcome.get("name")
                
                if best_outcome == "1":
                    return {
                        "type": f"{pred.get('home_team')} gagne",
                        "odds": min_odds,
                        "confidence": 0.55,
                        "market": "1X2 (Fallback)"
                    }
                elif best_outcome == "2":
                    return {
                        "type": f"{pred.get('away_team')} gagne",
                        "odds": min_odds,
                        "confidence": 0.55,
                        "market": "1X2 (Fallback)"
                    }
                elif best_outcome == "X":
                    return {
                        "type": "Match nul",
                        "odds": min_odds,
                        "confidence": 0.55,
                        "market": "1X2 (Fallback)"
                    }
            
            return None
        
        # Retourner la prédiction avec la meilleure confiance
        return valid_predictions[0]
    
    def generate_predictions(self):
        """Génère les meilleures prédictions pour les matchs sélectionnés."""
        logger.info("=== GÉNÉRATION DES PRÉDICTIONS ===")
        
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
            
            # Analyser tous les marchés et collecter les prédictions possibles
            all_predictions = []
            
            # Ajouter les informations d'équipe à toutes les prédictions
            match_info = {
                "home_team": home_team,
                "away_team": away_team
            }
            
            # Analyser le marché 1X2
            predictions_1x2 = self.analyze_1x2_market(markets, home_team, away_team)
            for p in predictions_1x2:
                p.update(match_info)
                all_predictions.append(p)
            
            # Analyser le marché BTTS
            predictions_btts = self.analyze_btts_market(markets)
            for p in predictions_btts:
                p.update(match_info)
                all_predictions.append(p)
            
            # Analyser les marchés over/under
            predictions_ou = self.analyze_over_under_markets(markets)
            for p in predictions_ou:
                p.update(match_info)
                all_predictions.append(p)
            
            # Analyser les scores exacts
            predictions_scores = self.analyze_exact_scores(markets)
            for p in predictions_scores:
                p.update(match_info)
                all_predictions.append(p)
            
            # Analyser la dominance d'équipe
            predictions_dominance = self.analyze_home_away_dominance(markets, home_team, away_team)
            for p in predictions_dominance:
                p.update(match_info)
                all_predictions.append(p)
            
            # Trouver la meilleure prédiction
            best_prediction = self.find_best_prediction(all_predictions, markets)
            
            if best_prediction:
                # Ajouter les informations supplémentaires
                best_prediction["match_id"] = match_id
                best_prediction["league_name"] = league_name
                best_prediction["start_timestamp"] = match.get("start_timestamp", 0)
                
                # Stocker la prédiction
                self.predictions[match_id] = best_prediction
                
                logger.info(f"  Prédiction pour {home_team} vs {away_team}: {best_prediction['type']} (Cote: {best_prediction['odds']})")
                logger.info(f"  Confiance: {best_prediction['confidence']:.2f}, Marché: {best_prediction['market']}")
            else:
                # Fallback: Créer une prédiction basée sur le favori du match
                if "1" in markets:
                    home_odds = away_odds = draw_odds = None
                    for outcome in markets["1"].get("outcomes", []):
                        if outcome.get("name") == "1":
                            home_odds = outcome.get("odds")
                        elif outcome.get("name") == "2":
                            away_odds = outcome.get("odds")
                        elif outcome.get("name") == "X":
                            draw_odds = outcome.get("odds")
                    
                    if home_odds and away_odds:
                        if home_odds <= away_odds:
                            fallback_pred = {
                                "match_id": match_id,
                                "home_team": home_team,
                                "away_team": away_team,
                                "league_name": league_name,
                                "start_timestamp": match.get("start_timestamp", 0),
                                "type": "1X",
                                "odds": 1.4,  # Valeur par défaut, à remplacer
                                "confidence": 0.6,
                                "market": "Double Chance (Fallback)"
                            }
                            
                            # Chercher la cote réelle
                            for market_id, market in markets.items():
                                if "double chance" in market.get("name", "").lower():
                                    for outcome in market.get("outcomes", []):
                                        if outcome.get("name") == "1X":
                                            fallback_pred["odds"] = outcome.get("odds")
                        else:
                            fallback_pred = {
                                "match_id": match_id,
                                "home_team": home_team,
                                "away_team": away_team,
                                "league_name": league_name,
                                "start_timestamp": match.get("start_timestamp", 0),
                                "type": "X2",
                                "odds": 1.4,  # Valeur par défaut, à remplacer
                                "confidence": 0.6,
                                "market": "Double Chance (Fallback)"
                            }
                            
                            # Chercher la cote réelle
                            for market_id, market in markets.items():
                                if "double chance" in market.get("name", "").lower():
                                    for outcome in market.get("outcomes", []):
                                        if outcome.get("name") == "X2":
                                            fallback_pred["odds"] = outcome.get("odds")
                        
                        self.predictions[match_id] = fallback_pred
                        logger.info(f"  Prédiction de secours pour {home_team} vs {away_team}: {fallback_pred['type']} (Cote: {fallback_pred['odds']})")
                else:
                    logger.warning(f"Impossible de générer une prédiction pour {home_team} vs {away_team}")
        
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
            message += f"🎯 *Prédiction:* {pred['type']}\n"
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
