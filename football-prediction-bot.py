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
        logger.info("Démarrage du bot de prédictions football...")
        
        # Sélectionner les matchs à venir
        self.select_upcoming_matches()
        
        # Si des matchs ont été trouvés
        if self.selected_matches:
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
            logger.error("Aucun match trouvé pour la période spécifiée. Arrêt du bot.")
    
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
                        logger.info(f"Nouvelle tentative dans {retry_delay} secondes...")
                        time.sleep(retry_delay)
            except Exception as e:
                logger.error(f"Erreur de connexion (tentative {attempt+1}/{max_retries}): {str(e)}")
                if attempt < max_retries - 1:
                    logger.info(f"Nouvelle tentative dans {retry_delay} secondes...")
                    time.sleep(retry_delay)
        
        logger.error("Échec de la requête après plusieurs tentatives.")
        return None
    
    def get_upcoming_matches(self):
        """Récupère les matchs à venir pour les prochaines heures."""
        # Définir la plage horaire pour les matchs (entre 01h00 et 07h00)
        now = datetime.now()
        start_time = datetime(now.year, now.month, now.day, 1, 0, 0)
        end_time = datetime(now.year, now.month, now.day, 7, 0, 0)
        
        # Si nous sommes déjà après 01h00, prenons les matchs de demain
        if now.hour >= 1:
            tomorrow = now + timedelta(days=1)
            start_time = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 1, 0, 0)
            end_time = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 7, 0, 0)
        
        start_timestamp = int(start_time.timestamp())
        end_timestamp = int(end_time.timestamp())
        
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
        
        logger.info(f"Recherche de matchs entre {start_time.strftime('%d/%m/%Y %H:%M')} et {end_time.strftime('%d/%m/%Y %H:%M')}...")
        
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
            for match in matches:
                match_timestamp = match.get("start_timestamp", 0)
                
                if start_timestamp <= match_timestamp <= end_timestamp:
                    # Ajouter le nom de la ligue aux informations du match
                    match["league_name"] = league_name
                    all_matches.append(match)
            
            logger.info(f"Trouvé {len([m for m in all_matches if m.get('league_name') == league_name])} match(s) dans la plage horaire spécifiée pour {league_name}")
            
            # Attendre un court moment entre les requêtes pour éviter les limites d'API
            time.sleep(0.5)
        
        return all_matches
    
    def select_upcoming_matches(self):
        """Sélectionne aléatoirement 2 ou 3 matchs parmi les matchs à venir."""
        all_matches = self.get_upcoming_matches()
        
        if not all_matches:
            logger.warning("Aucun match trouvé pour la période spécifiée.")
            return
        
        logger.info(f"Total des matchs trouvés dans la plage horaire spécifiée: {len(all_matches)}")
        
        # Choisir aléatoirement 2 ou 3 matchs
        num_matches = random.randint(2, 3)
        if len(all_matches) <= num_matches:
            self.selected_matches = all_matches
        else:
            self.selected_matches = random.sample(all_matches, num_matches)
        
        logger.info(f"Sélection de {len(self.selected_matches)} matchs pour les prédictions")
        
        # Afficher les matchs sélectionnés
        for i, match in enumerate(self.selected_matches):
            start_time = datetime.fromtimestamp(match.get("start_timestamp", 0))
            logger.info(f"Match {i+1}: {match.get('home_team')} vs {match.get('away_team')} - {match.get('league_name')} - {start_time.strftime('%d/%m/%Y %H:%M')}")
    
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
        logger.info("Génération des prédictions...")
        
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
            
            # Multiplier la cote totale
            self.coupon_total_odds *= self.predictions[match_id]["odds"]
        
        # Arrondir la cote totale
        self.coupon_total_odds = round(self.coupon_total_odds, 2)
        
        logger.info(f"Prédictions générées pour {len(self.predictions)} matchs avec une cote totale de {self.coupon_total_odds}")
    
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
        # Déterminer quand le dernier match se termine
        last_match_time = max([p["start_timestamp"] for _, p in self.predictions.items()])
        last_match_end = datetime.fromtimestamp(last_match_time) + timedelta(hours=2)  # Estimer 2h pour un match
        
        # Commencer à vérifier après la fin estimée du dernier match
        first_check = last_match_end + timedelta(minutes=5)
        
        now = datetime.now()
        if first_check < now:
            # Si c'est déjà après la fin estimée, commencer immédiatement
            logger.info("Vérification des résultats immédiate...")
            self.verify_results()
            # Puis vérifier toutes les 10 minutes
            schedule.every(10).minutes.do(self.verify_results)
        else:
            # Programmer la première vérification
            time_until_first_check = (first_check - now).total_seconds() / 60
            logger.info(f"Premier match terminé dans environ {round(time_until_first_check)} minutes. Première vérification programmée.")
            
            # Programmer pour la première vérification
            schedule.every(round(time_until_first_check)).minutes.do(self.verify_results)
            # Ensuite vérifier toutes les 10 minutes
            schedule.every(10).minutes.do(self.verify_results)
    
    def get_match_results(self, match_id):
        """Récupère les résultats d'un match terminé."""
        endpoint = f"/matches/{match_id}?mode=line&lng=en"
        response = self.make_api_request(endpoint)
        
        if not response or response.get("status") != "success":
            logger.warning(f"Impossible de récupérer les résultats pour le match ID: {match_id}")
            return None
        
        match_data = response.get("data", {})
        
        # Vérifier si le match est terminé
        if match_data.get("status") == "finished":
            return {
                "home_score": match_data.get("score_home", "?"),
                "away_score": match_data.get("score_away", "?"),
                "finished": True
            }
        
        return {"finished": False}
    
    def check_prediction_outcome(self, prediction, match_result):
        """Vérifie si une prédiction était correcte."""
        pred_type = prediction["prediction_type"]
        pred_value = prediction["prediction"]
        
        home_score = int(match_result["home_score"])
        away_score = int(match_result["away_score"])
        total_goals = home_score + away_score
        
        # Vérifier selon le type de prédiction
        if pred_type == "1X2":
            if pred_value == "1" and home_score > away_score:
                return True
            elif pred_value == "X" and home_score == away_score:
                return True
            elif pred_value == "2" and home_score < away_score:
                return True
        
        elif pred_type == "Total":
            if "Under 2.5" in pred_value and total_goals < 2.5:
                return True
            elif "Over 2.5" in pred_value and total_goals > 2.5:
                return True
            elif "Under 3.5" in pred_value and total_goals < 3.5:
                return True
            elif "Over 3.5" in pred_value and total_goals > 3.5:
                return True
        
        elif pred_type == "Double Chance":
            if "1X" in pred_value and (home_score >= away_score):
                return True
            elif "12" in pred_value and (home_score != away_score):
                return True
            elif "X2" in pred_value and (home_score <= away_score):
                return True
        
        elif pred_type == "Les deux équipes marquent":
            both_teams_scored = home_score > 0 and away_score > 0
            if pred_value == "Oui" and both_teams_scored:
                return True
            elif pred_value == "Non" and not both_teams_scored:
                return True
        
        return False
    
    def verify_results(self):
        """Vérifie les résultats des matchs et détermine si le coupon est gagnant."""
        logger.info("Vérification des résultats des matchs...")
        
        results = {}
        all_finished = True
        winning_predictions = 0
        
        for match_id, prediction in self.predictions.items():
            match_result = self.get_match_results(match_id)
            
            if not match_result:
                all_finished = False
                continue
            
            if not match_result.get("finished", False):
                all_finished = False
                continue
            
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
            logger.info("Tous les matchs sont terminés, envoi des résultats...")
            
            # Déterminer si le coupon est gagnant (toutes les prédictions doivent être correctes)
            coupon_is_winner = winning_predictions == len(self.predictions)
            
            # Envoyer le message de résultat
            self.send_results_to_telegram(results, coupon_is_winner)
            
            # Arrêter la planification
            return schedule.CancelJob
        else:
            logger.info("Certains matchs ne sont pas encore terminés, nouvelle vérification dans 10 minutes...")
    
    def format_results_message(self, results, coupon_is_winner):
        """Formate le message de résultat pour Telegram."""
        date_str = datetime.now().strftime("%d/%m/%Y")
        
        if coupon_is_winner:
            message = f"🏆 *COUPON GAGNANT - {date_str}* 🏆\n\n"
        else:
            message = f"❌ *COUPON PERDANT - {date_str}* ❌\n\n"
        
        message += f"📝 *ID du Coupon:* {self.coupon_id}\n\n"
        
        for i, (match_id, result_data) in enumerate(results.items()):
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

# Point d'entrée principal
if __name__ == "__main__":
    try:
        bot = FootballPredictionBot()
        bot.run()
    except Exception as e:
        logger.critical(f"Erreur fatale: {str(e)}")
