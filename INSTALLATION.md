# Installation (FR)

1. Crée un dépôt **public** sur GitHub, par ex. `medai-arxiv-daily`.
2. Envoie ces fichiers sur la branche `main` (glisser-déposer sur github.com → « uploading an existing file », ou `git push`).
   ⚠️ Le dossier `.github/` est caché : vérifie qu'il est bien envoyé.
3. **Settings → Secrets and variables → Actions → Variables → New repository variable** :
   - `GIT_NAME` = ton pseudo GitHub
   - `GIT_EMAIL` = ton email no-reply (`ID+pseudo@users.noreply.github.com`, visible dans Settings → Emails)
   Sans ces variables, les commits sont signés par le bot et **ne comptent pas** sur ton profil.
4. **Settings → Actions → General → Workflow permissions** → **Read and write permissions** → Save.
5. Onglet **Actions** → « Daily arXiv digest » → **Run workflow** pour le premier lancement.

## Personnaliser
- Thèmes et mots-clés : `config.json` (ajoute par ex. `"Digital twins": ["digital twin"]`).
- Heure : ligne `cron` dans `.github/workflows/daily.yml` (UTC).
- Tester en local : `python scripts/update.py`

## Bon à savoir
- arXiv ne publie pas le week-end : ces jours-là, seul le README (date de mise à jour) change, et le samedi un récap hebdo est créé dans `digests/weekly/`.
- Épingle le dépôt sur ton profil (Profil → Customize your pins) : c'est une vraie vitrine pour tes candidatures en IA médicale.
