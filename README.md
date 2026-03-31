# GitHub Pages -versio lounassivusta

Tämä paketti on tarkoitettu GitHub Pagesiin siten, että data haetaan GitHub Actionsilla ajastetusti.

## Tiedostot
- `index.html` = sivu
- `data/lunches.json` = viimeisin haettu data
- `scripts/fetch_lunches.py` = hakee lounaat lähdesivuilta
- `.github/workflows/pages.yml` = ajastaa haun ja julkaisee sivun GitHub Pagesiin

## Käyttöönotto
1. Pura zip omalle koneelle.
2. Lataa kaikki tiedostot GitHub-repoon.
3. GitHubissa: Settings -> Pages -> Source -> GitHub Actions
4. Mene Actions-välilehdelle ja aja workflow kerran käsin: "Build and deploy lunch page"
5. Sen jälkeen sivu päivittyy automaattisesti arkisin kaksi kertaa päivässä.

## Huomio
Jos lähdesivujen rakenne muuttuu, parseria pitää päivittää tiedostossa `scripts/fetch_lunches.py`.
