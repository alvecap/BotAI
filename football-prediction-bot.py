import http.client
import json
import random
import os
import time
import logging
import math
from datetime import datetime, timedelta
import pytz
import schedule
import requests

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('prediction_bot')

class FootballPredictionBot:
    def __init__(self):
        """Initialisation avec les variables d'environnement"""
        self.rapidapi_key = os.environ.get('RAPIDAPI_KEY')
        self.rapidapi_host = os.environ.get('RAPIDAPI_HOST', "1xbet-api.p.rapidapi.com")
        self.telegram_bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        self.telegram_channel_id = os.environ.get('TELEGRAM_CHANNEL_ID')
        self._check_env_variables()
        
        self.headers = {
            'x-rapidapi-key': self.rapidapi_key,
            'x-rapidapi-host': self.rapidapi_host
        }
        
        self.timezone = pytz.timezone('Africa/Brazzaville')
        self.predictions = {}
        self.coupon_total_odds = 1.0
        
        # Barème des cotes maximales
        self.max_odds = {
            1.5: 1.60,
            2.5: 2.50,
            3.5: 3.80,
            4.5: 5.50
        }
        
        self.min_odds = 1.15
        self.min_matches = 2
        self.max_matches = 5

        # Liste des IDs de ligue comme dans votre code initial
        self.league_ids = [1, 118, 148, 127, 110, 136, 251, 252, 253, 301, 302, 303, 304]

    def _check_env_variables(self):
        """Vérification des variables obligatoires"""
        required_vars = {
            'RAPIDAPI_KEY': self.rapidapi_key,
            'TELEGRAM_BOT_TOKEN': self.telegram_bot_token,
            'TELEGRAM_CHANNEL_ID': self.telegram_channel_id
        }
        missing = [name for name, val in required_vars.items() if not val]
        if missing:
            raise EnvironmentError(f"Variables manquantes: {', '.join(missing)}")

    def run(self):
        """Point d'entrée principal"""
        try:
            # Génération immédiate du premier coupon
            self.generate_coupon()
            
            # Planification quotidienne à 07h00
            schedule.every().day.at("07:00").do(self.generate_coupon)
            
            logger.info("Bot démarré - Premier coupon généré immédiatement")
            logger.info("Prochaine exécution programmée à 07h00 chaque jour")
            
            while True:
                schedule.run_pending()
                time.sleep(60)
                
        except Exception as e:
            logger.error(f"Erreur critique: {str(e)}", exc_info=True)

    def generate_coupon(self):
        """Génère un nouveau coupon de paris"""
        logger.info("=== DÉBUT GÉNÉRATION COUPON ===")
        self.predictions = {}
        self.coupon_total_odds = 1.0
        
        matches = self.get_todays_matches()
        if not matches:
            logger.error("Aucun match disponible aujourd'hui")
            return
            
        selected_matches = random.sample(matches, min(self.max_matches * 2, len(matches)))
        valid_matches = 0
        replacement_attempts = 0
        max_replacements = len(matches)  # Limite basée sur le nombre total de matchs
        
        while valid_matches < self.min_matches and replacement_attempts < max_replacements:
            for match in selected_matches[:]:
                if valid_matches >= self.max_matches:
                    break
                    
                prediction = self.analyze_match(match)
                if prediction:
                    self.predictions[match['id']] = prediction
                    valid_matches += 1
                    selected_matches.remove(match)
            
            # Si pas assez de matchs valides, on remplace
            if valid_matches < self.min_matches and len(matches) > len(selected_matches):
                new_candidates = [m for m in matches if m not in selected_matches]
                if new_candidates:
                    selected_matches.extend(random.sample(new_candidates, 1))
                    replacement_attempts += 1
        
        if self.predictions:
            self.coupon_total_odds = round(math.prod(
                pred['odds'] for pred in self.predictions.values()
            ), 2)
            self.send_coupon()
        else:
            logger.error("Impossible de générer un coupon valide")

    def get_todays_matches(self):
        """Récupère tous les matchs du jour avec les endpoints originaux"""
        now = datetime.now(self.timezone)
        today_start = datetime(now.year, now.month, now.day, 0, 0, 0).replace(tzinfo=self.timezone)
        today_end = today_start + timedelta(days=1)
        
        start_timestamp = int(today_start.timestamp())
        end_timestamp = int(today_end.timestamp())
        
        all_matches = []
        
        # Utilisation exacte des endpoints originaux comme fourni
        for league_id in self.league_ids:
            try:
                endpoint = f"/matches?sport_id=1&league_id={league_id}&mode=line&lng=en"
                conn = http.client.HTTPSConnection(self.rapidapi_host)
                conn.request("GET", endpoint, headers=self.headers)
                res = conn.getresponse()
                
                if res.status == 200:
                    data = json.loads(res.read().decode('utf-8'))
                    if data.get('status') == 'success':
                        for match in data.get('data', []):
                            if (start_timestamp <= match.get('start_timestamp', 0) <= end_timestamp
                                and self.is_valid_match(match)):
                                all_matches.append(match)
            except Exception as e:
                logger.error(f"Erreur API pour ligue {league_id}: {str(e)}")
            finally:
                conn.close()
            time.sleep(0.5)  # Respect du rate limiting
            
        logger.info(f"Nombre de matchs trouvés: {len(all_matches)}")
        return all_matches

    def is_valid_match(self, match):
        """Vérifie si un match est valide pour analyse"""
        return (
            match.get('home_team') and match.get('away_team')
            and len(match['home_team']) >= 3 and len(match['away_team']) >= 3
            and match.get('id') and match.get('start_timestamp')
            and match.get('league')
        )

    def analyze_match(self, match):
        """Analyse un match et retourne une prédiction valide"""
        match_id = match['id']
        logger.info(f"Analyse du match {match['home_team']} vs {match['away_team']}")
        
        try:
            # Utilisation de l'endpoint original pour les cotes
            endpoint = f"/matches/{match_id}/markets?mode=line&lng=en"
            conn = http.client.HTTPSConnection(self.rapidapi_host)
            conn.request("GET", endpoint, headers=self.headers)
            res = conn.getresponse()
            
            if res.status == 200:
                data = json.loads(res.read().decode('utf-8'))
                if data.get('status') == 'success':
                    return self.extract_prediction(data.get('data', {}), match)
        except Exception as e:
            logger.error(f"Erreur analyse match {match_id}: {str(e)}")
        finally:
            conn.close()
            
        return None

    def extract_prediction(self, markets, match):
        """Extrait la meilleure prédiction selon le barème"""
        # Extraction des cotes avec la structure originale
        over_goals = {}
        home_over = {}
        away_over = {}
        
        # Total goals (market 17)
        if '17' in markets:
            for outcome in markets['17'].get('outcomes', []):
                name = outcome.get('name', '').lower()
                if 'over' in name:
                    if '1.5' in name: over_goals[1.5] = outcome.get('odds')
                    elif '2.5' in name: over_goals[2.5] = outcome.get('odds')
                    elif '3.5' in name: over_goals[3.5] = outcome.get('odds')
                    elif '4.5' in name: over_goals[4.5] = outcome.get('odds')
        
        # Home totals (market 15)
        if '15' in markets:
            for outcome in markets['15'].get('outcomes', []):
                name = outcome.get('name', '').lower()
                if 'over' in name:
                    if '1.5' in name: home_over[1.5] = outcome.get('odds')
                    elif '2.5' in name: home_over[2.5] = outcome.get('odds')
        
        # Away totals (market 62)
        if '62' in markets:
            for outcome in markets['62'].get('outcomes', []):
                name = outcome.get('name', '').lower()
                if 'over' in name:
                    if '1.5' in name: away_over[1.5] = outcome.get('odds')
                    elif '2.5' in name: away_over[2.5] = outcome.get('odds')
        
        # Vérification pour +3.5 buts (nécessite +4.5 valide)
        if (self.is_valid_odd(over_goals.get(3.5), 3.5) 
            and self.is_valid_odd(over_goals.get(4.5), 4.5)):
            return {
                'home_team': match['home_team'],
                'away_team': match['away_team'],
                'league': match['league'],
                'time': datetime.fromtimestamp(match['start_timestamp'], self.timezone).strftime('%H:%M'),
                'type': '+3,5 buts',
                'odds': over_goals[3.5]
            }
        
        # Vérification pour +2.5 buts (nécessite over 1.5 des deux équipes)
        elif (self.is_valid_odd(over_goals.get(2.5), 2.5)
              and self.is_valid_odd(home_over.get(1.5), 1.5)
              and self.is_valid_odd(away_over.get(1.5), 1.5)):
            return {
                'home_team': match['home_team'],
                'away_team': match['away_team'],
                'league': match['league'],
                'time': datetime.fromtimestamp(match['start_timestamp'], self.timezone).strftime('%H:%M'),
                'type': '+2,5 buts',
                'odds': over_goals[2.5]
            }
        
        # Vérification pour +1.5 buts
        elif self.is_valid_odd(over_goals.get(1.5), 1.5):
            return {
                'home_team': match['home_team'],
                'away_team': match['away_team'],
                'league': match['league'],
                'time': datetime.fromtimestamp(match['start_timestamp'], self.timezone).strftime('%H:%M'),
                'type': '+1,5 buts',
                'odds': over_goals[1.5]
            }
            
        return None

    def is_valid_odd(self, odd, goal_type):
        """Vérifie si une cote respecte le barème"""
        return (odd and self.min_odds <= odd <= self.max_odds.get(goal_type, 999))

    def send_coupon(self):
        """Envoie le coupon sur Telegram avec la mise en forme exacte demandée"""
        message = "<b>PRÉDICTIONS DU JOUR</b>\n\n"
        
        for pred in self.predictions.values():
            message += (
                f"<b>{pred['league']}</b>\n"
                f"<b>{pred['home_team']} vs {pred['away_team']}</b>\n"
                f"Heure : {pred['time']}\n"
                f"Prédiction : {pred['type']}\n"
                f"Cote : {pred['odds']}\n\n"
            )
        
        message += f"<b>COTE TOTALE : {self.coupon_total_odds}</b>"
        
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage",
                json={
                    'chat_id': self.telegram_channel_id,
                    'text': message,
                    'parse_mode': 'HTML'
                },
                timeout=10
            )
            logger.info("Coupon envoyé avec succès" if response.ok else "Échec envoi coupon")
        except Exception as e:
            logger.error(f"Erreur envoi Telegram: {str(e)}")

if __name__ == "__main__":
    bot = FootballPredictionBot()
    bot.run()
