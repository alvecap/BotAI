import http.client
import json
import random
import os
import time
import logging
from datetime import datetime, timedelta
import requests
from tabulate import tabulate
import schedule

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
        self.coupon_id = datetime.now().strftime("%Y%m%d%H%M")
        self.coupon_total_odds = 0
        
        # Variables spécifiques pour le stockage des IDs de matchs
        self.match_ids = []  # IDs des matchs pour vérification
        self.match_details = {}  # Détails des matchs pour référence (ID -> informations)
        self.match_end_times = {}  # Heures de fin estimées pour chaque match (ID -> datetime)
    
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
        
    def run(self):
        """Fonction principale pour exécuter le bot."""
        logger.info("=== DÉMARRAGE DU BOT DE PRÉDICTIONS FOOTBALL ===")
        logger.info(f"Date/heure actuelle: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        
        # Sélectionner les matchs à venir entre 10h00 et 11h00
        self.select_upcoming_matches()
        
        # Si des matchs ont été trouvés
        if self.selected_matches:
            # Enregistrer les IDs des matchs et leurs détails
            self.store_match_ids()
            
            # Générer des prédictions
            self.generate_predictions()
            
            # Envoyer le coupon sur Telegram
            self.send_predictions_to_telegram()
            
            # Programmer la vérification des résultats
            self.schedule_results_verification()
            
            # Garder le script en fonctionnement
            logger.info("Bot en attente des résultats des matchs...")
            while True:
                schedule.run_pending()
                time.sleep(60)
        else:
            logger.error("Aucun match trouvé pour la période spécifiée (10h-11h). Arrêt du bot.")
    
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
    
    def get_upcoming_matches(self):
        """Récupère les matchs à venir entre 10h et 11h aujourd'hui."""
        # Définir la plage horaire pour les matchs (entre 10h00 et 11h00 aujourd'hui)
        now = datetime.now()
        today_10am = datetime(now.year, now.month, now.day, 10, 0, 0)
        today_11am = datetime(now.year, now.month, now.day, 11, 0, 0)
        
        start_timestamp = int(today_10am.timestamp())
        end_timestamp = int(today_11am.timestamp())
        
        logger.info(f"Recherche de matchs entre {today_10am.strftime('%d/%m/%Y %H:%M')} et {today_11am.strftime('%d/%m/%Y %H:%M')}...")
        logger.info(f"Timestamps: {start_timestamp} - {end_timestamp}")
        
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
            
            # Filtrer les matchs qui se déroulent dans la plage horaire spécifiée
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
                logger.info(f"Trouvé {league_matches_count} match(s) entre 10h-11h pour {league_name}")
            
            # Attendre un court moment entre les requêtes pour éviter les limites d'API
            time.sleep(0.5)
        
        logger.info(f"Total des matchs trouvés entre 10h-11h: {len(all_matches)}")
        return all_matches
    
    def select_upcoming_matches(self):
        """Sélectionne 1 ou 2 matchs parmi les matchs entre 10h-11h."""
        all_matches = self.get_upcoming_matches()
        
        if not all_matches:
            logger.warning("Aucun match trouvé entre 10h-11h.")
            return
        
        # Limiter à 1 ou 2 matchs maximum
        max_matches = min(2, len(all_matches))
        num_matches = random.randint(1, max_matches)
        
        if len(all_matches) <= num_matches:
            self.selected_matches = all_matches
        else:
            self.selected_matches = random.sample(all_matches, num_matches)
        
        logger.info(f"=== SÉLECTION DE {len(self.selected_matches)} MATCH(S) POUR LES PRÉDICTIONS ===")
        
        # Afficher les matchs sélectionnés
        for i, match in enumerate(self.selected_matches):
            start_timestamp = match.get("start_timestamp", 0)
            start_time = datetime.fromtimestamp(start_timestamp)
            
            # Calculer l'heure de fin estimée (2h après le début pour un match de football)
            end_time = start_time + timedelta(hours=2)
            
            logger.info(f"Match {i+1}: {match.get('home_team')} vs {match.get('away_team')} - {match.get('league_name')}")
            logger.info(f"  ID: {match.get('id')}")
            logger.info(f"  Début: {start_time.strftime('%d/%m/%Y %H:%M')}")
            logger.info(f"  Fin estimée: {end_time.strftime('%d/%m/%Y %H:%M')}")
    
    def store_match_ids(self):
        """Stocke les IDs des matchs sélectionnés pour vérification ultérieure."""
        logger.info("=== STOCKAGE DES IDs DE MATCHS POUR VÉRIFICATION ===")
        
        for match in self.selected_matches:
            match_id = match.get("id")
            self.match_ids.append(match_id)
            
            # Stocker les détails du match
            self.match_details[match_id] = {
                "home_team": match.get("home_team"),
                "away_team": match.get("away_team"),
                "league_name": match.get("league_name"),
                "league_id": match.get("league_id"),
                "start_timestamp": match.get("start_timestamp")
            }
            
            # Calculer et stocker l'heure de fin estimée
            start_time = datetime.fromtimestamp(match.get("start_timestamp", 0))
            end_time = start_time + timedelta(hours=2)  # Estimer 2h pour un match de football
            self.match_end_times[match_id] = end_time
            
            logger.info(f"ID du match: {match_id} | {match.get('home_team')} vs {match.get('away_team')}")
            logger.info(f"  Heure de fin estimée: {end_time.strftime('%d/%m/%Y %H:%M')}")
        
        # Afficher un résumé
        logger.info(f"IDs des matchs stockés: {self.match_ids}")
        
        # Sauvegarder ces informations dans un fichier pour référence
        self.save_match_ids_to_file()
    
    def save_match_ids_to_file(self):
        """Sauvegarde les IDs des matchs et leurs détails dans un fichier."""
        try:
            data_to_save = {
                "coupon_id": self.coupon_id,
                "match_ids": self.match_ids,
                "match_details": self.match_details,
                "end_times": {match_id: end_time.strftime('%Y-%m-%d %H:%M:%S') 
                              for match_id, end_time in self.match_end_times.items()}
            }
            
            filename = f"match_ids_{self.coupon_id}.json"
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, indent=2, ensure_ascii=False)
            
            logger.info(f"IDs des matchs sauvegardés dans {filename}")
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde des IDs: {str(e)}")
    
    def get_match_odds(self, match_id):
        """Récupère les cotes pour un match spécifique."""
        endpoint = f"/matches/{match_id}/markets?mode=line&lng=en"
        response = self.make_api_request(endpoint)
        
        if not response or response.get("status") != "success":
            logger.warning(f"Impossible de récupérer les cotes pour le match ID: {match_id}")
            return None
        
        return response.get("data", {})
    
    def generate_predictions(self):
        """Génère des prédictions aléatoires pour les matchs sélectionnés."""
        logger.info("=== GÉNÉRATION DES PRÉDICTIONS ===")
        
        # Types de prédictions possibles
        prediction_types = [
            {"id": "1", "name": "1X2", "outcomes": ["1", "X", "2"]},
            {"id": "17", "name": "Total", "outcomes": ["Under 2.5", "Over 2.5", "Under 3.5", "Over 3.5"]},
            {"id": "12", "name": "Double Chance", "outcomes": ["1X", "12", "X2"]},
            {"id": "9", "name": "Les deux équipes marquent", "outcomes": ["Oui", "Non"]}
        ]
        
        self.coupon_total_odds = 1.0
        
        for match in self.selected_matches:
            match_id = match.get("id")
            home_team = match.get("home_team")
            away_team = match.get("away_team")
            
            logger.info(f"Génération de prédiction pour {home_team} vs {away_team} (ID: {match_id})...")
            
            # Récupérer les cotes pour ce match
            markets = self.get_match_odds(match_id)
            
            if not markets:
                logger.warning(f"Pas de cotes disponibles pour {home_team} vs {away_team}, génération aléatoire")
                
                # Générer une prédiction et une cote aléatoire si les cotes ne sont pas disponibles
                pred_type = random.choice(prediction_types)
                outcome = random.choice(pred_type["outcomes"])
                odds = round(random.uniform(1.5, 3.0), 2)
                
                self.predictions[match_id] = {
                    "match_id": match_id,
                    "home_team": home_team,
                    "away_team": away_team,
                    "league_name": match.get("league_name", "Ligue inconnue"),
                    "start_timestamp": match.get("start_timestamp", 0),
                    "prediction_type": pred_type["name"],
                    "prediction": outcome,
                    "odds": odds
                }
                
                logger.info(f"  Prédiction générée: {pred_type['name']} - {outcome} (Cote: {odds})")
            else:
                # Choisir un type de prédiction aléatoire
                pred_type = random.choice(prediction_types)
                pred_id = pred_type["id"]
                
                # Vérifier si ce type de marché est disponible
                if pred_id in markets:
                    # Choisir un résultat aléatoire dans ce marché
                    outcomes = markets[pred_id].get("outcomes", [])
                    if outcomes:
                        outcome = random.choice(outcomes)
                        
                        self.predictions[match_id] = {
                            "match_id": match_id,
                            "home_team": home_team,
                            "away_team": away_team,
                            "league_name": match.get("league_name", "Ligue inconnue"),
                            "start_timestamp": match.get("start_timestamp", 0),
                            "prediction_type": pred_type["name"],
                            "prediction": outcome.get("name"),
                            "odds": outcome.get("odds")
                        }
                        
                        logger.info(f"  Prédiction: {pred_type['name']} - {outcome.get('name')} (Cote: {outcome.get('odds')})")
                    else:
                        # Si pas d'options dans ce marché, générer aléatoirement
                        outcome = random.choice(pred_type["outcomes"])
                        odds = round(random.uniform(1.5, 3.0), 2)
                        
                        self.predictions[match_id] = {
                            "match_id": match_id,
                            "home_team": home_team,
                            "away_team": away_team,
                            "league_name": match.get("league_name", "Ligue inconnue"),
                            "start_timestamp": match.get("start_timestamp", 0),
                            "prediction_type": pred_type["name"],
                            "prediction": outcome,
                            "odds": odds
                        }
                        
                        logger.info(f"  Prédiction générée: {pred_type['name']} - {outcome} (Cote: {odds})")
                else:
                    # Si ce type de marché n'est pas disponible, générer aléatoirement
                    outcome = random.choice(pred_type["outcomes"])
                    odds = round(random.uniform(1.5, 3.0), 2)
                    
                    self.predictions[match_id] = {
                        "match_id": match_id,
                        "home_team": home_team,
                        "away_team": away_team,
                        "league_name": match.get("league_name", "Ligue inconnue"),
                        "start_timestamp": match.get("start_timestamp", 0),
                        "prediction_type": pred_type["name"],
                        "prediction": outcome,
                        "odds": odds
                    }
                    
                    logger.info(f"  Prédiction générée: {pred_type['name']} - {outcome} (Cote: {odds})")
            
            # Multiplier la cote totale
            self.coupon_total_odds *= self.predictions[match_id]["odds"]
        
        # Arrondir la cote totale
        self.coupon_total_odds = round(self.coupon_total_odds, 2)
        
        logger.info(f"Prédictions générées pour {len(self.predictions)} match(s) avec une cote totale de {self.coupon_total_odds}")
    
    def format_prediction_message(self):
        """Formate le message de prédiction pour Telegram."""
        date_str = datetime.now().strftime("%d/%m/%Y")
        
        message = f"🔮 *COUPON DE PRÉDICTIONS - {date_str}* 🔮\n\n"
        message += f"📝 *ID du Coupon:* {self.coupon_id}\n\n"
        
        for i, (match_id, pred) in enumerate(self.predictions.items()):
            start_time = datetime.fromtimestamp(pred["start_timestamp"]).strftime("%H:%M")
            
            message += f"*MATCH {i+1}:*\n"
            message += f"🏆 {pred['league_name']}\n"
            message += f"⚽ {pred['home_team']} vs {pred['away_team']} ({start_time})\n"
            message += f"🎯 *Prédiction:* {pred['prediction_type']} - {pred['prediction']}\n"
            message += f"💰 *Cote:* {pred['odds']}\n\n"
        
        message += f"*📈 COTE TOTALE DU COUPON: {self.coupon_total_odds}*\n\n"
        message += "⏳ _Les résultats seront vérifiés automatiquement après les matchs_"
        
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
    
    def schedule_results_verification(self):
        """Planifie la vérification des résultats des matchs."""
        # Trouver le dernier match à se terminer
        if not self.match_end_times:
            logger.error("Aucune heure de fin estimée disponible. Impossible de planifier la vérification.")
            return
        
        # Obtenir l'heure de fin la plus tardive
        last_end_time = max(self.match_end_times.values())
        
        # Ajouter 5 minutes pour s'assurer que les résultats sont disponibles
        first_check_time = last_end_time + timedelta(minutes=5)
        
        now = datetime.now()
        logger.info(f"Heure actuelle: {now.strftime('%d/%m/%Y %H:%M')}")
        logger.info(f"Dernière heure de fin estimée: {last_end_time.strftime('%d/%m/%Y %H:%M')}")
        logger.info(f"Première vérification prévue à: {first_check_time.strftime('%d/%m/%Y %H:%M')}")
        
        if first_check_time < now:
            # Si l'heure de vérification est déjà passée, commencer immédiatement
            logger.info("L'heure de vérification est déjà passée, vérification immédiate...")
            self.verify_results()
            # Puis vérifier toutes les 10 minutes
            schedule.every(10).minutes.do(self.verify_results)
        else:
            # Programmer la première vérification
            time_until_first_check = (first_check_time - now).total_seconds() / 60
            logger.info(f"Première vérification dans environ {round(time_until_first_check)} minutes")
            
            # Programmer pour la première vérification
            schedule.every(round(time_until_first_check)).minutes.do(self.verify_results)
            # Ensuite vérifier toutes les 10 minutes
            schedule.every(10).minutes.do(self.verify_results)
    
    def get_match_results(self, match_id):
        """Récupère les résultats d'un match terminé."""
        logger.info(f"Vérification des résultats pour le match ID: {match_id}")
        
        # Récupérer les détails du match pour référence
        match_details = self.match_details.get(match_id, {})
        home_team = match_details.get("home_team", "Équipe inconnue")
        away_team = match_details.get("away_team", "Équipe inconnue")
        
        endpoint = f"/matches/{match_id}?mode=line&lng=en"
        response = self.make_api_request(endpoint)
        
        if not response or response.get("status") != "success":
            logger.warning(f"Impossible de récupérer les résultats pour {home_team} vs {away_team} (ID: {match_id})")
            return None
        
        match_data = response.get("data", {})
        
        # Afficher le statut du match pour le débogage
        status = match_data.get("status", "inconnu")
        logger.info(f"Statut du match {match_id} ({home_team} vs {away_team}): {status}")
        
        # Vérifier tous les champs possibles qui pourraient indiquer que le match est terminé
        is_finished = (
            status == "finished" or
            match_data.get("is_live") == False or  # Le match n'est plus en direct
            match_data.get("time_status") == 3 or  # Possiblement un code pour "terminé"
            match_data.get("status_name") == "finished"  # Autre champ possible
        )
        
        # Afficher des détails supplémentaires pour le débogage
        logger.info(f"  is_live: {match_data.get('is_live')}")
        logger.info(f"  time_status: {match_data.get('time_status')}")
        logger.info(f"  status_name: {match_data.get('status_name')}")
        
        if is_finished:
            home_score = match_data.get("score_home", "?")
            away_score = match_data.get("score_away", "?")
            
            logger.info(f"Match terminé: {home_team} {home_score} - {away_score} {away_team}")
            
            return {
                "home_score": home_score,
                "away_score": away_score,
                "finished": True
            }
        else:
            logger.info(f"Le match n'est pas encore terminé: {home_team} vs {away_team}")
            return {"finished": False}
    
    def check_prediction_outcome(self, prediction, match_result):
        """Vérifie si une prédiction était correcte."""
        pred_type = prediction["prediction_type"]
        pred_value = prediction["prediction"]
        
        home_score = int(match_result["home_score"])
        away_score = int(match_result["away_score"])
        total_goals = home_score + away_score
        
        logger.info(f"Vérification de la prédiction: {pred_type} - {pred_value}")
        logger.info(f"Score final: {home_score} - {away_score} (Total: {total_goals})")
        
        # Vérifier selon le type de prédiction
        if pred_type == "1X2":
            if pred_value == "1" and home_score > away_score:
                logger.info("Prédiction CORRECTE: Victoire à domicile")
                return True
            elif pred_value == "X" and home_score == away_score:
                logger.info("Prédiction CORRECTE: Match nul")
                return True
            elif pred_value == "2" and home_score < away_score:
                logger.info("Prédiction CORRECTE: Victoire à l'extérieur")
                return True
        
        elif pred_type == "Total":
            if "Under 2.5" in pred_value and total_goals < 2.5:
                logger.info("Prédiction CORRECTE: Moins de 2.5 buts")
                return True
            elif "Over 2.5" in pred_value and total_goals > 2.5:
                logger.info("Prédiction CORRECTE: Plus de 2.5 buts")
                return True
            elif "Under 3.5" in pred_value and total_goals < 3.5:
                logger.info("Prédiction CORRECTE: Moins de 3.5 buts")
                return True
            elif "Over 3.5" in pred_value and total_goals > 3.5:
                logger.info("Prédiction CORRECTE: Plus de 3.5 buts")
                return True
        
        elif pred_type == "Double Chance":
            if "1X" in pred_value and (home_score >= away_score):
                logger.info("Prédiction CORRECTE: 1X (Victoire domicile ou nul)")
                return True
            elif "12" in pred_value and (home_score != away_score):
                logger.info("Prédiction CORRECTE: 12 (Pas de match nul)")
                return True
            elif "X2" in pred_value and (home_score <= away_score):
                logger.info("Prédiction CORRECTE: X2 (Match nul ou victoire extérieure)")
                return True
        
        elif pred_type == "Les deux équipes marquent":
            both_teams_scored = home_score > 0 and away_score > 0
            if pred_value == "Oui" and both_teams_scored:
                logger.info("Prédiction CORRECTE: Les deux équipes ont marqué")
                return True
            elif pred_value == "Non" and not both_teams_scored:
                logger.info("Prédiction CORRECTE: Au moins une équipe n'a pas marqué")
                return True
        
        logger.info("Prédiction INCORRECTE")
        return False
    
    def verify_results(self):
        """Vérifie les résultats des matchs et détermine si le coupon est gagnant."""
        logger.info("=== VÉRIFICATION DES RÉSULTATS DES MATCHS ===")
        logger.info(f"Heure actuelle: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        logger.info(f"IDs des matchs à vérifier: {self.match_ids}")
        
        results = {}
        all_finished = True
        winning_predictions = 0
        
        for match_id in self.match_ids:
            # Récupérer les informations du match pour référence
            match_details = self.match_details.get(match_id, {})
            home_team = match_details.get("home_team", "Équipe inconnue")
            away_team = match_details.get("away_team", "Équipe inconnue")
            
            logger.info(f"Vérification du match: {home_team} vs {away_team} (ID: {match_id})")
            
            match_result = self.get_match_results(match_id)
            
            if not match_result:
                logger.warning(f"Pas de résultat disponible pour {home_team} vs {away_team}")
                all_finished = False
                continue
            
            if not match_result.get("finished", False):
                logger.info(f"Le match {home_team} vs {away_team} n'est pas encore terminé.")
                all_finished = False
                continue
            
            # Le match est terminé, vérifier la prédiction
            logger.info(f"Le match {home_team} vs {away_team} est terminé.")
            
            # Récupérer la prédiction pour ce match
            if match_id not in self.predictions:
                logger.error(f"Aucune prédiction trouvée pour le match ID: {match_id}")
                continue
            
            prediction = self.predictions[match_id]
            
            # Déterminer si la prédiction était correcte
            is_winner = self.check_prediction_outcome(prediction, match_result)
            
            results[match_id] = {
                "prediction": prediction,
                "result": match_result,
                "is_winner": is_winner
            }
            
            if is_winner:
                winning_predictions += 1
        
        # Si tous les matchs sont terminés, envoyer les résultats
        if all_finished:
            logger.info("=== TOUS LES MATCHS SONT TERMINÉS ===")
            
            # Déterminer si le coupon est gagnant (toutes les prédictions doivent être correctes)
            coupon_is_winner = winning_predictions == len(self.predictions)
            
            if coupon_is_winner:
                logger.info("COUPON GAGNANT! Toutes les prédictions étaient correctes.")
            else:
                logger.info(f"COUPON PERDANT. {winning_predictions}/{len(self.predictions)} prédictions correctes.")
            
            # Envoyer le message de résultat
            self.send_results_to_telegram(results, coupon_is_winner)
            
            # Arrêter la planification
            logger.info("Fin des vérifications. Nettoyage...")
            return schedule.CancelJob
        else:
            logger.info("Certains matchs ne sont pas encore terminés, nouvelle vérification dans 10 minutes...")
            
            # Afficher les matchs en attente
            pending_matches = []
            for match_id in self.match_ids:
                if match_id not in results or not results[match_id]["result"].get("finished", False):
                    match_details = self.match_details.get(match_id, {})
                    pending_matches.append(f"{match_details.get('home_team')} vs {match_details.get('away_team')} (ID: {match_id})")
            
            logger.info(f"Matchs en attente: {', '.join(pending_matches)}")
    
    def format_results_message(self, results, coupon_is_winner):
        """Formate le message de résultat pour Telegram."""
        date_str = datetime.now().strftime("%d/%m/%Y")
        
        if coupon_is_winner:
            message = f"🏆 *COUPON GAGNANT - {date_str}* 🏆\n\n"
        else:
            message = f"❌ *COUPON PERDANT - {date_str}* ❌\n\n"
        
        message += f"📝 *ID du Coupon:* {self.coupon_id}\n\n"
        
        for i, match_id in enumerate(self.match_ids):
            if match_id not in results:
                continue
                
            result_data = results[match_id]
            pred = result_data["prediction"]
            res = result_data["result"]
            is_winner = result_data["is_winner"]
            
            message += f"*MATCH {i+1}:*\n"
            message += f"🏆 {pred['league_name']}\n"
            message += f"⚽ {pred['home_team']} vs {pred['away_team']}\n"
            message += f"📊 *Score final:* {res['home_score']} - {res['away_score']}\n"
            message += f"🎯 *Prédiction:* {pred['prediction_type']} - {pred['prediction']} (Cote: {pred['odds']})\n"
            
            if is_winner:
                message += "✅ *CORRECT*\n\n"
            else:
                message += "❌ *INCORRECT*\n\n"
        
        message += f"*📈 COTE TOTALE DU COUPON: {self.coupon_total_odds}*\n\n"
        
        if coupon_is_winner:
            message += "🎉 *FÉLICITATIONS! TOUTES LES PRÉDICTIONS ÉTAIENT CORRECTES* 🎉"
        else:
            message += "😔 *DÉSOLÉ, CERTAINES PRÉDICTIONS ÉTAIENT INCORRECTES* 😔"
        
        return message
    
    def send_results_to_telegram(self, results, coupon_is_winner):
        """Envoie les résultats sur le canal Telegram."""
        message = self.format_results_message(results, coupon_is_winner)
        
        logger.info(f"Envoi des résultats sur Telegram (Coupon {'gagnant' if coupon_is_winner else 'perdant'})...")
        success = self.send_to_telegram(message)
        
        if success:
            logger.info("Résultats envoyés avec succès")
        else:
            logger.error("Échec de l'envoi des résultats")
            
        # Sauvegarder les résultats dans un fichier pour référence
        self.save_results_to_file(results, coupon_is_winner)
    
    def save_results_to_file(self, results, coupon_is_winner):
        """Sauvegarde les résultats dans un fichier pour référence."""
        try:
            data_to_save = {
                "coupon_id": self.coupon_id,
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "is_winner": coupon_is_winner,
                "results": {}
            }
            
            # Formater les résultats pour la sauvegarde
            for match_id, result_data in results.items():
                pred = result_data["prediction"]
                res = result_data["result"]
                
                data_to_save["results"][match_id] = {
                    "home_team": pred["home_team"],
                    "away_team": pred["away_team"],
                    "league_name": pred["league_name"],
                    "prediction_type": pred["prediction_type"],
                    "prediction": pred["prediction"],
                    "odds": pred["odds"],
                    "score_home": res["home_score"],
                    "score_away": res["away_score"],
                    "is_winner": result_data["is_winner"]
                }
            
            filename = f"results_{self.coupon_id}.json"
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Résultats sauvegardés dans {filename}")
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde des résultats: {str(e)}")

# Point d'entrée principal
if __name__ == "__main__":
    try:
        bot = FootballPredictionBot()
        bot.run()
    except Exception as e:
        logger.critical(f"Erreur fatale: {str(e)}")
        # Afficher la trace complète de l'erreur pour faciliter le débogage
        import traceback
        logger.critical(traceback.format_exc())
