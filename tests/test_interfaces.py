"""CLI, API et MCP (les tests API / MCP sont sautés si fastapi / mcp ne sont pas installés)."""
import pytest

from sourcia.cli import build_parser, main

from conftest import ROOT


def test_parser_has_all_steps():
    p = build_parser()
    for cmd in ["doctor", "add-site", "add-folder", "import-catalog", "download", "extract", "qualify", "fiche",
                "index", "search", "select", "stats", "eval", "demo", "serve", "mcp", "demande", "formation",
                "valider-formation", "referentiel"]:
        assert p.parse_args(["demo"] if cmd == "demo" else [cmd] + {"add-site": ["u"], "add-folder": ["f"],
                            "import-catalog": ["f", "--source", "s"], "fiche": ["x"], "search": ["q"],
                            "select": ["q"], "eval": ["trouver"], "demande": ["d.yaml"],
                            "valider-formation": ["dossier", "--par", "X"], "referentiel": ["liste"]}.get(cmd, []))
    a = p.parse_args(["formation", "--demande-fichier", "d.yaml", "--niveau", "cap", "--capacites", "C4.2,C4.3"])
    assert a.niveau == "cap" and a.capacites == "C4.2,C4.3"


def test_cli_demande_and_referentiel(tmp_path, capsys):
    from sourcia.core.demande import Demande

    main(["demande", str(tmp_path / "d.yaml")])
    d = Demande.load(tmp_path / "d.yaml")
    assert d.profil == "formateur" and "quiz" in d.sorties
    for name in ("btsa_sorgho_c4", "agriculteurs_secheresse", "capa_paturage"):
        Demande.load(ROOT / "config" / "demandes" / f"{name}.yaml")      # les exemples sont valides
    main(["-c", str(ROOT / "config/test.yaml"), "referentiel", "voir", "btsa-acsagri"])
    out = capsys.readouterr().out
    assert "C4.2" in out and "Ajuster" in out


def test_cli_demo_runs(tmp_path, capsys, monkeypatch):
    cfg = tmp_path / "t.yaml"
    cfg.write_text((ROOT / "config/test.yaml").read_text(encoding="utf-8").replace("data/test-run", str(tmp_path / "d")),
                   encoding="utf-8")
    main(["-c", str(cfg), "demo"])
    out = capsys.readouterr().out
    assert "essai 2023" in out and "Index" in out
    main(["-c", str(cfg), "eval", "qualifier"])
    assert "exactitude" in capsys.readouterr().out


def test_api(demo_ctx):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from sourcia.api.app import create_app

    c = TestClient(create_app(ctx=demo_ctx))
    assert "SourcIA" in c.get("/").text
    assert c.get("/api/etat").json()["fiches"] == 8
    assert "btsa-acsagri" in [x["id"] for x in c.get("/api/referentiels").json()]
    d = {"sujet": "sorgho fourrager", "diplomante": True, "diplome": "btsa-acsagri", "capacites": ["C4.2"], "nombre_sources": 5}
    r = c.post("/api/selection", json={"demande": d}).json()
    assert r["documents"] and r["exports"]
    assert c.get("/api/export/" + r["exports"][0]).status_code == 200
    assert c.get("/api/export/..%2F..%2Fsecret").status_code == 404
    f = c.get(f"/api/fiche/{r['documents'][0]['id']}").json()
    assert "evidence" in f["champs"]["annee"]
    fo = c.post("/api/formation", json={"demande": d, "doc_ids": [x["id"] for x in r["documents"]], "quiz": 1}).json()
    assert fo["rattachements"] and fo["rattachements"][0]["capacite"] == "C4.2"
    v = c.post(f"/api/formation/{fo['dossier']}/rattachements", json={"valideur": "X", "decisions": [{"n": 1, "valide": True}]})
    assert v.json()["valides"] == 1


def test_mcp_server_builds(demo_ctx):
    pytest.importorskip("mcp")
    from sourcia.mcp_server.server import build_server

    assert build_server(demo_ctx) is not None
