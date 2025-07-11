# CROUS-Logement Alert

Petit service **Flask** qui surveille le site officiel *trouverunlogement.lescrous.fr* et :

* accepte jusqu’à **65 abonnés** (e‑mail + ville) ;
* envoie **immédiatement** un courriel si un logement existe déjà lors de l’inscription ;
* répète les vérifications **4 × par jour** (08 h / 12 h / 16 h / 20 h – fuseau *Europe/Paris*) ;
* limite le spam grâce à un *cool‑down* de **12 h** par abonné.

> **Stack** : Python ≥ 3.9 · Flask · APScheduler · Requests · SQLite  
> **Front** : Bootstrap 5 + Choices.js (menu déroulant filtrable)

---

## Installation rapide

```bash
# 1 – Cloner et créer un venv
git clone https://github.com/votre-compte/crous-logement-alert.git
cd crous-logement-alert
python -m venv .venv
source .venv/bin/activate            # sous Windows : .venv\Scripts\activate.ps1

# 2 – Installer les dépendances
pip install -r requirements.txt

# 3 – Configurer les variables sensibles
nano .env                            # renseigner SMTP_USER, SMTP_PASSWORD, etc.

# 4 – Lancer
python app.py
# → http://127.0.0.1:5000
```

### Exemple de fichier `.env`

```dotenv
# Flask
SECRET_KEY = 9b8c2b6a959be02bbab34d256a20b39e

# SMTP (Gmail)
SMTP_HOST     = smtp.gmail.com
SMTP_PORT     = 587
SMTP_USER     = votreadresse@gmail.com
SMTP_PASSWORD = motDePasseApplication16Car
EMAIL_FROM    = "Alertes CROUS <votreadresse@gmail.com>"
```

> 🔑 **Gmail** : active l’A2F puis crée un **mot de passe d’application** 16 caractères.  
> ⚠️ N’utilise jamais ton mot de passe principal.

---

## Fichiers clés

| Fichier / dossier      | Rôle                                                          |
|------------------------|---------------------------------------------------------------|
| `app.py`               | Serveur Flask, scheduler, scraping, envoi d’e‑mails           |
| `requirements.txt`     | Dépendances PyPI                                              |
| `.env.example`         | Modèle de configuration SMTP / Flask                          |
| `static/cities.json`   | Liste des villes (`{"cities":[{"label":"Lyon"}, …]}`)         |
| `subscriptions.db`     | Base SQLite (créée au démarrage)                              |

---

## Paramètres rapides

| Variable              | Effet                                             | Valeur par défaut |
|-----------------------|---------------------------------------------------|-------------------|
| `MAX_SUBSCRIBERS`     | Quota global d’abonnés                            | 65                |
| `ALERT_COOLDOWN`      | Délai minimal entre deux mails pour un abonné     | 12 h              |
| `hour="8,12,16,20"` | Créneaux quotidiens de vérification               | 4                 |

Pour ajouter d’autres académies, élargis simplement le dictionnaire `ACADEMIES` dans `app.py`.

---

## Déploiement (optionnel)

```dockerfile
# Dockerfile minimal
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
EXPOSE 5000
CMD ["python", "app.py"]
```

Exécution :

```bash
docker build -t crous-alert .
docker run -d -p 5000:5000 --env-file .env crous-alert
```

---

## Licence

MIT — faites-en bon usage, contribuez… et trouvez rapidement un logement 🏠
