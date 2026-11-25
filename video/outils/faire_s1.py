"""Écrit compositions/s1-fiches.html : le mur des vraies fiches du catalogue (titres de capture/titres.txt)."""
import html
import json
from pathlib import Path

ICI = Path(__file__).resolve().parent.parent
rows = [json.loads(line.rstrip(",")) for line in (ICI / "capture/titres.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
cols = [rows[0::3], rows[1::3], rows[2::3]]


def row(t):
    titre, source, annee = t
    meta = ", ".join(x for x in (source, annee) if x)
    return f'<li><span class="t">{html.escape(titre)}</span><span class="m">{html.escape(meta)}</span></li>'


colonnes = "\n".join(
    f'      <ul class="col" id="s1-col{i}">' + "".join(row(t) for t in c + c) + "</ul>" for i, c in enumerate(cols, 1)
)

page = f"""<template>
  <style>
    @font-face {{ font-family: "Atkinson Hyperlegible"; font-weight: 400; src: url("assets/app/fonts/atkinson-hyperlegible-normal.woff2") format("woff2"); }}
    @font-face {{ font-family: "Atkinson Hyperlegible"; font-weight: 700; src: url("assets/app/fonts/atkinson-hyperlegible-gras.woff2") format("woff2"); }}
    #root {{ position: absolute; inset: 0; overflow: hidden; background: var(--craie); font-family: "Atkinson Hyperlegible", sans-serif; }}
    #s1-mur {{ position: absolute; top: -40px; right: -40px; width: 1380px; height: 1200px; display: flex; gap: 22px; }}
    .col {{ list-style: none; width: 440px; display: flex; flex-direction: column; gap: 16px; }}
    .col li {{ background: var(--blanc); border: 2px solid var(--trait); border-radius: 18px; padding: 18px 22px; }}
    .col .t {{ display: block; font-weight: 700; font-size: 25px; line-height: 1.25; color: var(--bleuet);
      text-decoration: underline; text-underline-offset: 5px; text-decoration-thickness: 2px; }}
    .col .m {{ display: block; margin-top: 6px; font-size: 21px; color: var(--terre-douce); }}
    #s1-voile {{ position: absolute; inset: 0;
      background: linear-gradient(90deg, var(--craie) 0%, var(--craie) 38%, rgba(247,248,243,.86) 50%, rgba(247,248,243,0) 70%); }}
    #s1-compteur {{ position: absolute; left: 130px; top: 300px; width: 720px; }}
    #s1-nombre {{ font-family: var(--titre); font-weight: 700; font-size: 300px; line-height: .9; color: var(--bleuet);
      letter-spacing: -.02em; font-variant-numeric: tabular-nums; }}
    #s1-legende {{ margin-top: 26px; font-family: var(--titre); font-weight: 700; font-size: 58px; line-height: 1.12; color: var(--bleuet); }}
    #s1-sources {{ margin-top: 22px; font-size: 30px; color: var(--terre-douce); }}
  </style>
  <div id="root" data-composition-id="s1" data-width="1920" data-height="1080">
    <div id="s1-mur">
{colonnes}
    </div>
    <div id="s1-voile"></div>
    <div id="s1-compteur">
      <div id="s1-nombre">0</div>
      <div id="s1-legende" class="clip" data-start="0" data-duration="8.7">fiches techniques<br />dans le catalogue</div>
      <div id="s1-sources" class="clip" data-start="0" data-duration="8.7">Arvalis, Terres Inovia, chambres d’agriculture</div>
    </div>
  </div>
  <script>
    const tl = gsap.timeline({{ paused: true }});
    // le mur défile (vitesse constante : c'est le catalogue qui « coule »), une colonne sur deux plus vite
    tl.fromTo("#s1-col1", {{ y: 0 }}, {{ y: -820, duration: 8.7, ease: "none" }}, 0);
    tl.fromTo("#s1-col2", {{ y: -520 }}, {{ y: -1500, duration: 8.7, ease: "none" }}, 0);
    tl.fromTo("#s1-col3", {{ y: -200 }}, {{ y: -1120, duration: 8.7, ease: "none" }}, 0);
    // le compteur monte jusqu'au vrai nombre de documents
    const n = {{ v: 87 }};
    tl.fromTo(n, {{ v: 87 }}, {{ v: 603, duration: 2.6, ease: "power3.out",
      onUpdate: () => {{ document.getElementById("s1-nombre").textContent = Math.round(n.v); }} }}, 0.3);
    tl.fromTo("#s1-legende", {{ opacity: 0, filter: "blur(8px)" }}, {{ opacity: 1, filter: "blur(0px)", duration: 0.2 }}, 0.6);
    tl.fromTo("#s1-sources", {{ opacity: 0, filter: "blur(8px)" }}, {{ opacity: 1, filter: "blur(0px)", duration: 0.2 }}, 2.2);
    // sortie : le compteur s'efface, le mur passe devant (il devient le fond flou du plan 2)
    tl.to("#s1-compteur", {{ opacity: 0, filter: "blur(8px)", duration: 0.22, ease: "power3.in" }}, 8.3);
    tl.to("#s1-voile", {{ opacity: 0, duration: 0.5, ease: "power2.inOut" }}, 8.1);
    window.__timelines["s1"] = tl;
  </script>
</template>
"""
(ICI / "compositions").mkdir(exist_ok=True)
(ICI / "compositions/s1-fiches.html").write_text(page, encoding="utf-8")
print("s1 écrit")
