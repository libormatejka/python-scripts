# GPX Heatmap

Vykreslí GPX trasy jako heatmapu na tmavou mapovou podkladovou vrstvu (CartoDB DarkMatter).
Překrývající se trasy svítí jasněji — čím víc přejezdů, tím intenzivnější barva.

## Použití

```bash
cd ~/projects/python-scripts/gpx-mapper

# Zpracuje všechny .gpx soubory ze složky maps/
docker run --rm -v ./maps:/app/maps -v ./output:/app/output gpx-mapper -o output/heatmap.png

# Nebo přes docker compose
docker compose run --rm gpx-mapper
```

Výstup se uloží do `output/heatmap.png`.

## Přidání GPX souborů

Stačí hodit `.gpx` soubory do složky `maps/` — název souboru nevadí.

Pokud soubor pochází ze Strava bulk exportu a název obsahuje typ aktivity,
barva se přiřadí automaticky:

| Vzor v názvu | Barva |
|---|---|
| `-Ride` | cyan |
| `-Run` | červená |
| `-Hike`, `-Walk` | růžová |
| ostatní | červená |

## Parametry

```bash
docker run --rm -v ./maps:/app/maps -v ./output:/app/output gpx-mapper \
  [soubory nebo nic] \        # bez souborů vezme vše z maps/
  -o output/heatmap.png \     # výstupní soubor
  --width 4096 \              # šířka výstupu v px (výchozí: 2048)
  --height 4096 \             # výška výstupu v px (výchozí: 2048)
  --zoom 13 \                 # zoom level mapy (viz tabulka níže, výchozí: auto)
  --line-width 3 \            # tloušťka čáry v px (výchozí: 3)
  --blur 1.5 \                # glow efekt – poloměr rozmazání (výchozí: 1.5, 0 = vypnuto)
  --color red \               # barva pro všechny trasy: red / cyan / pink
  --padding 40                # okraj kolem tras v px (výchozí: 40)
```

## Zoom level

Zoom se volí automaticky tak, aby se všechny trasy vešly do výstupního obrázku.
Pro ruční ovládání použij `--zoom`:

| Zoom | Pokrytí | Vhodné pro |
|---|---|---|
| 10 | kraj / větší region | celé Čechy, víc měst |
| 11 | oblast ~100 km | kraj, okolí města |
| 12 | oblast ~50 km | velké město + okolí |
| 13 | město | město s předměstím |
| 14 | čtvrť / část města | centrum + okolí |
| 15 | detailní pohled | konkrétní část města |
| 16+ | velmi detailní | ulice, trail |

**Tip:** Čím vyšší zoom, tím víc mapových dlaždic se musí stáhnout a tím déle render trvá.

## Sestavení Docker image

```bash
cd ~/projects/python-scripts/gpx-mapper
docker build -t gpx-mapper .
```

## Závislosti

- `gpxpy` — parsování GPX souborů
- `numpy` — aditivní skládání vrstev
- `Pillow` — vykreslování a export
- `requests` — stahování mapových dlaždic
