#!/usr/bin/env python3
"""
Script de collecte d'APIs et webservices fonctionnels depuis Internet
Auteur: Assistant Claude
"""

import requests
from bs4 import BeautifulSoup
import json
import csv
import time
import random
import re
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('api_collector.log'),
        logging.StreamHandler()
    ]
)


class APICollector:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

        # Sites connus pour lister des APIs
        self.api_directories = [
            'https://publicapis.sznm.dev/',
            'https://github.com/public-apis/public-apis',
            'https://rapidapi.com/collection/list-of-free-apis',
            'https://apilist.fun/',
            'https://any-api.com/',
            'https://www.programmableweb.com/apis/directory'
        ]

        # Patterns pour identifier les APIs
        self.api_patterns = [
            r'https?://[^/\s]+/api',
            r'https?://api\.[^/\s]+',
            r'https?://[^/\s]+\.api\.',
            r'https?://[^/\s]+/v\d+',
            r'https?://[^/\s]+/rest',
            r'https?://[^/\s]+/graphql'
        ]

        self.found_apis = []
        self.tested_apis = []

    def get_page_content(self, url, timeout=10):
        """Récupère le contenu d'une page web"""
        try:
            response = self.session.get(url, timeout=timeout)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            logging.warning(f"Erreur lors de la récupération de {url}: {e}")
            return None

    def extract_links_from_html(self, html_content, base_url):
        """Extrait tous les liens d'une page HTML"""
        soup = BeautifulSoup(html_content, 'html.parser')
        links = []

        # Extraire tous les liens href
        for link in soup.find_all('a', href=True):
            href = link['href']
            full_url = urljoin(base_url, href)
            links.append(full_url)

        # Extraire les URLs depuis le texte (regex)
        text_content = soup.get_text()
        for pattern in self.api_patterns:
            matches = re.findall(pattern, text_content, re.IGNORECASE)
            links.extend(matches)

        return list(set(links))  # Supprimer les doublons

    def is_api_url(self, url):
        """Vérifie si une URL ressemble à une API"""
        url_lower = url.lower()
        api_indicators = [
            'api', 'rest', 'graphql', 'webhook', 'endpoint',
            '/v1/', '/v2/', '/v3/', '.json', '.xml'
        ]

        return any(indicator in url_lower for indicator in api_indicators)

    def test_api_endpoint(self, url, timeout=5):
        """Teste si un endpoint API est fonctionnel"""
        try:
            # Tester d'abord avec HEAD pour économiser la bande passante
            response = self.session.head(url, timeout=timeout, allow_redirects=True)

            # Si HEAD échoue, essayer GET
            if response.status_code >= 400:
                response = self.session.get(url, timeout=timeout)

            # Analyser la réponse
            api_info = {
                'url': url,
                'status_code': response.status_code,
                'content_type': response.headers.get('content-type', ''),
                'server': response.headers.get('server', ''),
                'is_functional': response.status_code < 400,
                'response_time': response.elapsed.total_seconds(),
                'supports_cors': 'access-control-allow-origin' in response.headers,
                'requires_auth': response.status_code == 401,
                'rate_limited': response.status_code == 429
            }

            # Essayer de détecter le type d'API
            content_type = response.headers.get('content-type', '').lower()
            if 'json' in content_type:
                api_info['type'] = 'REST/JSON'
            elif 'xml' in content_type:
                api_info['type'] = 'REST/XML'
            elif 'graphql' in url.lower():
                api_info['type'] = 'GraphQL'
            else:
                api_info['type'] = 'Unknown'

            return api_info

        except requests.RequestException as e:
            return {
                'url': url,
                'status_code': 0,
                'error': str(e),
                'is_functional': False
            }

    def search_github_apis(self, query="public api", max_results=50):
        """Recherche d'APIs sur GitHub"""
        github_api_url = f"https://api.github.com/search/repositories"
        params = {
            'q': f"{query} language:python",
            'sort': 'stars',
            'order': 'desc',
            'per_page': max_results
        }

        try:
            response = self.session.get(github_api_url, params=params)
            if response.status_code == 200:
                data = response.json()
                github_apis = []

                for repo in data.get('items', []):
                    # Extraire les URLs potentielles du README
                    readme_url = f"https://api.github.com/repos/{repo['full_name']}/readme"
                    readme_response = self.session.get(readme_url)

                    if readme_response.status_code == 200:
                        readme_data = readme_response.json()
                        # Le contenu est en base64
                        import base64
                        content = base64.b64decode(readme_data['content']).decode('utf-8')

                        # Extraire les URLs d'APIs
                        for pattern in self.api_patterns:
                            matches = re.findall(pattern, content, re.IGNORECASE)
                            github_apis.extend(matches)

                    time.sleep(0.1)  # Rate limiting pour GitHub API

                return list(set(github_apis))

        except requests.RequestException as e:
            logging.error(f"Erreur lors de la recherche GitHub: {e}")
            return []

    def collect_from_directories(self):
        """Collecte des APIs depuis les répertoires connus"""
        all_links = []

        for directory in self.api_directories:
            logging.info(f"Collecte depuis: {directory}")
            content = self.get_page_content(directory)

            if content:
                links = self.extract_links_from_html(content, directory)
                api_links = [link for link in links if self.is_api_url(link)]
                all_links.extend(api_links)

                logging.info(f"Trouvé {len(api_links)} liens API potentiels")

            # Délai pour éviter d'être bloqué
            time.sleep(random.uniform(1, 3))

        return list(set(all_links))

    def test_apis_parallel(self, urls, max_workers=10):
        """Teste les APIs en parallèle"""
        functional_apis = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Soumettre toutes les tâches
            future_to_url = {
                executor.submit(self.test_api_endpoint, url): url
                for url in urls
            }

            # Récupérer les résultats
            for future in as_completed(future_to_url):
                result = future.result()
                if result.get('is_functional'):
                    functional_apis.append(result)
                    logging.info(f"API fonctionnelle trouvée: {result['url']}")

                # Petit délai pour éviter de surcharger
                time.sleep(0.1)

        return functional_apis

    def save_results(self, apis, format='json'):
        """Sauvegarde les résultats dans différents formats"""
        timestamp = time.strftime("%Y%m%d_%H%M%S")

        if format == 'json':
            filename = f"apis_collected_{timestamp}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(apis, f, indent=2, ensure_ascii=False)

        elif format == 'csv':
            filename = f"apis_collected_{timestamp}.csv"
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                if apis:
                    fieldnames = apis[0].keys()
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(apis)

        logging.info(f"Résultats sauvegardés dans: {filename}")
        return filename

    def run_collection(self):
        """Lance la collecte complète"""
        logging.info("Début de la collecte d'APIs...")

        # 1. Collecter depuis les répertoires
        logging.info("Phase 1: Collecte depuis les répertoires d'APIs")
        directory_apis = self.collect_from_directories()

        # 2. Recherche sur GitHub
        logging.info("Phase 2: Recherche sur GitHub")
        github_apis = self.search_github_apis()

        # 3. Combiner toutes les URLs
        all_apis = list(set(directory_apis + github_apis))
        logging.info(f"Total d'APIs collectées: {len(all_apis)}")

        # 4. Tester les APIs
        logging.info("Phase 3: Test des APIs")
        functional_apis = self.test_apis_parallel(all_apis[:100])  # Limiter pour l'exemple

        # 5. Filtrer les APIs vraiment fonctionnelles
        working_apis = [api for api in functional_apis if api.get('is_functional')]

        logging.info(f"APIs fonctionnelles trouvées: {len(working_apis)}")

        # 6. Sauvegarder les résultats
        json_file = self.save_results(working_apis, 'json')
        csv_file = self.save_results(working_apis, 'csv')

        return working_apis, json_file, csv_file


def main():
    """Fonction principale"""
    collector = APICollector()

    try:
        working_apis, json_file, csv_file = collector.run_collection()

        print(f"\n{'=' * 50}")
        print(f"COLLECTE TERMINÉE")
        print(f"{'=' * 50}")
        print(f"APIs fonctionnelles trouvées: {len(working_apis)}")
        print(f"Fichiers générés:")
        print(f"  - JSON: {json_file}")
        print(f"  - CSV: {csv_file}")
        print(f"{'=' * 50}")

        # Afficher quelques exemples
        if working_apis:
            print(f"\nExemples d'APIs trouvées:")
            for i, api in enumerate(working_apis[:5]):
                print(f"{i + 1}. {api['url']} (Status: {api['status_code']})")

    except KeyboardInterrupt:
        logging.info("Collecte interrompue par l'utilisateur")
    except Exception as e:
        logging.error(f"Erreur durant la collecte: {e}")


if __name__ == "__main__":
    main()