#!/usr/bin/env python3
"""
Extrae equipos, clasificación y calendario/resultados de la Liga Cántabra de Pádel
(federacioncantabradepadel.com) y los guarda en CSV (separador ";", abren bien en Excel).

Uso:
    pip install requests beautifulsoup4
    python liga_padel.py                      # toda la liga (id 28942), ambos géneros, todas las fases y grupos
    python liga_padel.py --id 28942 --salida datos
    python liga_padel.py --file respuesta.html   # prueba offline con un HTML guardado (un solo grupo)

Genera en la carpeta de salida:
    partidos.csv, clasificacion.csv, equipos.csv
"""
import argparse
import csv
import os
import re
import time

import requests
from bs4 import BeautifulSoup

BASE = "https://www.federacioncantabradepadel.com/"
URL = BASE + "Liga_Calendario"
HEADERS = {"User-Agent": "Mozilla/5.0 (consulta personal de calendarios)"}
PAUSA = 1.0  # segundos entre peticiones, para no cargar el servidor


def limpiar(texto):
    return re.sub(r"\s+", " ", texto).strip()


def descargar(params):
    r = requests.get(URL, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    r.encoding = "iso-8859-1"  # la web sirve en latin-1
    time.sleep(PAUSA)
    return r.text


def opciones(soup, select_id, excluir):
    sel = soup.find("select", id=select_id)
    if not sel:
        return []
    salida = []
    for o in sel.find_all("option"):
        v = o.get("value", "").strip()
        if v and v not in excluir:
            salida.append((v, limpiar(o.get_text())))
    return salida


def parsear(html, ctx):
    """Devuelve (partidos, clasificacion) de una página de grupo."""
    soup = BeautifulSoup(html, "html.parser")
    tablas = soup.select("div.table-responsive table")
    if len(tablas) < 2:
        return [], []
    cal, clas = tablas[0], tablas[1]

    # --- Calendario: matriz local (filas) x visitante (columnas) ---
    filas = cal.find_all("tr")
    cabecera = [limpiar(td.get_text()) for td in filas[0].find_all("td")][1:]
    por_jornada = max(len(cabecera) // 2, 1)
    partidos = []
    for fila in filas[1:]:
        tds = fila.find_all("td")
        if not tds:
            continue
        local = limpiar(tds[0].get_text())
        for visitante, td in zip(cabecera, tds[1:]):
            a = td.find("a", href=re.compile(r"partido="))
            if not a:
                continue  # celda vacía (diagonal)
            n = int(re.search(r"partido=(\d+)", a["href"]).group(1))
            estado = (td.get("class") or [""])[0]
            lineas = [limpiar(x) for x in a.get_text("\n").split("\n") if limpiar(x)]
            p = {
                **ctx,
                "partido": n,
                "jornada_aprox": (n - 1) // por_jornada + 1,
                "local": local,
                "visitante": visitante,
                "estado": estado,  # cercanos / confecha / cerrados / ultima / sinacta / sinvalidar
                "fecha_texto": "",
                "hora": "",
                "tandas": "",
                "lugar": "",
                "resultado": "",
            }
            if estado == "cerrados":
                p["resultado"] = lineas[0] if lineas else ""
            elif estado == "confecha":
                m = re.match(r"(.+?)\s+(\d{1,2}:\d{2})$", lineas[0]) if lineas else None
                if m:
                    p["fecha_texto"], p["hora"] = m.group(1), m.group(2)
                elif lineas:
                    p["fecha_texto"] = lineas[0]
                for extra in lineas[1:]:
                    if extra.lower().startswith("tandas"):
                        p["tandas"] = extra.split(":", 1)[-1].strip()
                    else:
                        p["lugar"] = extra
            else:  # cercanos, ultima...: rango de fechas
                p["fecha_texto"] = lineas[0] if lineas else ""
            partidos.append(p)

    # --- Clasificación ---
    columnas = ["posicion", "equipo", "enfrentamientos", "puntos", "partidos_disputados",
                "partidos_ganados", "sets_favor", "sets_contra", "average_sets",
                "juegos_favor", "juegos_contra", "average_juegos"]
    clasif = []
    for fila in clas.find_all("tr", class_="lineas"):
        tds = [limpiar(td.get_text()) for td in fila.find_all("td")]
        if len(tds) < len(columnas):
            continue
        a = fila.find("a", href=re.compile(r"IdEquipo="))
        id_equipo = re.search(r"IdEquipo=(\d+)", a["href"]).group(1) if a else ""
        fila_d = dict(zip(columnas, tds))
        clasif.append({**ctx, "id_equipo": id_equipo, **fila_d})
    return partidos, clasif


def guardar(ruta, filas):
    if not filas:
        return
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(filas)
    print(f"  {ruta}: {len(filas)} filas")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default="28942", help="id de la liga (parámetro id de la URL)")
    ap.add_argument("--salida", default="datos_liga")
    ap.add_argument("--file", help="parsear un HTML guardado en vez de descargar")
    args = ap.parse_args()

    os.makedirs(args.salida, exist_ok=True)
    todos_partidos, toda_clasif = [], []

    if args.file:
        with open(args.file, "rb") as f:
            crudo = f.read()
        try:  # un HTML guardado desde el navegador suele estar en UTF-8
            html = crudo.decode("utf-8")
        except UnicodeDecodeError:
            html = crudo.decode("iso-8859-1")
        ctx = {"genero": "", "fase": "", "grupo_id": "", "grupo": ""}
        todos_partidos, toda_clasif = parsear(html, ctx)
    else:
        for genero in ("F", "M"):
            base = {"id": args.id, "genero": genero, "grupo": "-", "jornada": "--"}
            soup = BeautifulSoup(descargar({**base, "fase": 0}), "html.parser")
            fases = opciones(soup, "fase", {"0"}) or [("1", "Fase I")]
            for fase_id, fase_nombre in fases:
                soup = BeautifulSoup(descargar({**base, "fase": fase_id}), "html.parser")
                for grupo_id, grupo_nombre in opciones(soup, "grupo", {"-"}):
                    print(f"{genero} | {fase_nombre} | {grupo_nombre}")
                    html = descargar({**base, "fase": fase_id, "grupo": grupo_id})
                    ctx = {"genero": genero, "fase": fase_nombre,
                           "grupo_id": grupo_id, "grupo": grupo_nombre}
                    p, c = parsear(html, ctx)
                    todos_partidos += p
                    toda_clasif += c

    equipos = [{k: c[k] for k in ("genero", "fase", "grupo_id", "grupo", "id_equipo", "equipo")}
               for c in toda_clasif]
    print("Guardando:")
    guardar(os.path.join(args.salida, "partidos.csv"), todos_partidos)
    guardar(os.path.join(args.salida, "clasificacion.csv"), toda_clasif)
    guardar(os.path.join(args.salida, "equipos.csv"), equipos)


if __name__ == "__main__":
    main()

