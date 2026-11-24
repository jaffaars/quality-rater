"""Tests hors ligne de rater.py et bench.py : site local sans sitemap en Latin-1, cache, CSV, fusion de bancs."""
import functools, http.server, importlib.util, json, os, re, subprocess, sys, tempfile, threading

repo = os.path.abspath(sys.argv[1])
spec = importlib.util.spec_from_file_location("rater", os.path.join(repo, "rater.py"))
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
ok = lambda cond, label: print(("OK   " if cond else "ECHEC") + " " + label)

# --- mini-site local : pas de sitemap, Latin-1, contact seulement dans les mentions
site = tempfile.mkdtemp(prefix="qr-site-")
long_p = "<p>" + "Contenu original sur la torréfaction du café vert, avec mesures et essais. " * 30 + "</p>"
pages = {
	"index.html": '<html><head><meta charset="iso-8859-1"><title>Café maison</title></head><body><nav>'
		'<a href="/torrefaction.html">Torréfaction</a> <a href="/tag/x/">Tag</a> <a href="/mentions-legales/">Mentions légales</a>'
		'</nav><main><h1>Café maison</h1>' + long_p + '</main></body></html>',
	"torrefaction.html": '<html><head><meta charset="iso-8859-1"><title>Torréfaction</title></head><body><main><article>'
		'<header><h1>Torréfier son café à la poêle</h1><p class="byline">Par Jeanne</p></header>' + long_p
		+ '<a href="/mouture.html">Mouture</a></article></main></body></html>',
	"mouture.html": '<html><head><meta charset="iso-8859-1"><meta name="robots" content="noindex"><title>Mouture</title></head>'
		'<body><main>' + long_p + '</main></body></html>',
	"mentions-legales/index.html": '<html><head><meta charset="iso-8859-1"></head><body><main><h1>Mentions légales</h1>'
		'<p>Éditrice : Jeanne Martin, jeanne [at] exemple.test. Hébergeur : OVH. Directrice de la publication : Jeanne Martin.</p>'
		'</main></body></html>',
}
for name, body in pages.items():
	path = os.path.join(site, name)
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "w", encoding="iso-8859-1") as f:
		f.write(body)
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=site)
http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
root = f"http://127.0.0.1:{srv.server_port}/"

found = r.crawl(root, 5, re.compile(r.DEFAULT_EXCLUDE, re.I))
urls = [p["url"] for p in found]
ok(any(u.endswith("/torrefaction.html") for u in urls), "crawl sans sitemap : page trouvee par les liens")
ok(not any("mouture" in u for u in urls), "page noindex ecartee")
ok(not any("/tag/" in u for u in urls), "archive ecartee")
t = next(p for p in found if p["url"].endswith("/torrefaction.html"))
ok("torréfaction" in t["text"].lower(), "Latin-1 decode (accents intacts)")
ok(t["headings"][:1] == ["H1: Torréfier son café à la poêle"], "H1 dans l'en-tete de l'article")
sig = r.site_signals(root)
ok(sig.get("contact", {}).get("via_mentions") is True, "contact trouve via l'e-mail des mentions")
ok(sig["mentions_legales"].get("directeur") and sig["mentions_legales"].get("hebergeur"), "mentions : directrice et hebergeur")
print("     faits du site :", r.site_facts(sig))
srv.shutdown()

# --- extrait debut + fin
txt = "A" * 9000 + "B" * 9000 + "FIN"
ex = r.excerpt(txt, 12000)
ok(len(ex) < 12100 and ex.startswith("A") and ex.endswith("FIN"), "extrait garde le debut et la fin")

# --- JSON-LD : auteur designe par @id, puis repris plus loin en simple reference
blocks = [json.dumps({"@context": "https://schema.org", "@graph": [
	{"@type": "Person", "@id": "https://ex.test/auteur/1#author", "name": "Jeanne Martin", "url": "https://ex.test/auteur/1"},
	{"@type": "Article", "headline": "Torrefier", "author": {"@id": "https://ex.test/auteur/1#author"}},
	{"@type": "WebPage", "author": {"@id": "https://ex.test/auteur/1#author"}}]})]
ok(r.jsonld_facts(blocks)[0] == "Jeanne Martin", "auteur par @id garde meme si une simple reference suit sa definition")

# --- la charte editoriale compte comme page A propos (adresse ou texte du lien)
path_re, text_re = r.SITE_PAGES["a_propos"]
ok(re.search(path_re, "/charte-editoriale") and re.search(path_re, "/notre-charte-editoriale-2024/")
	and re.search(text_re, "charte éditoriale") and not re.search(path_re, "/charte-graphique"), "charte editoriale reconnue comme A propos")

# --- requetes Search Console d'une page redirigee : rattachees via l'adresse demandee
qs = {r.page_key("https://ex.test/ancien-titre-123"): {"url": "https://ex.test/ancien-titre-123", "queries": [(9, 90, "cafe vert")], "clicks": 9}}
pgs = [{"url": "https://ex.test/nouveau-titre-123", "requested": "https://ex.test/ancien-titre-123"}, {"url": "https://ex.test/autre"}]
ok(hasattr(r, "attach_queries") and r.attach_queries(pgs, qs) == 1 and pgs[0]["queries"] == [(9, 90, "cafe vert")] and pgs[1]["queries"] == [],
	"page redirigee : requetes de l'adresse demandee gardees")

# --- tableur : pas de formule
ok(r.cell("=HYPERLINK(1)") == "'=HYPERLINK(1)" and r.cell("ok") == "ok" and r.cell(3) == 3, "cellules protegees des formules")

# --- cache JSONL : rechargement, ligne coupee toleree, cle sensible au reglage de reflexion
tmp = tempfile.mkdtemp(prefix="qr-cache-")
cpath = os.path.join(tmp, "c.jsonl")
c = r.Cache(cpath)
cfg = {"base": "b", "model": "m", "reasoning": "none"}
k1 = c.key(cfg, "S", "U")
c.put(k1, {"x": 1})
with open(cpath, "a", encoding="utf-8") as f:
	f.write('{"k": "coupe')
c2 = r.Cache(cpath)
ok(c2.get(k1) == {"x": 1}, "cache JSONL relu malgre une ligne coupee")
ok(c.key(dict(cfg, reasoning="high"), "S", "U") != k1, "cle de cache differente si --reasoning change")

# --- liste de sites
lp = os.path.join(tmp, "sites.txt")
with open(lp, "w", encoding="utf-8") as f:
	f.write("# reseau\nexemple.fr\nhttps://www.exemple.fr/\n\nautre.fr  # commentaire\n")
ok(r.read_sites(lp) == ["https://exemple.fr", "https://autre.fr"], "liste de sites : doublons www et commentaires")

# --- export Search Console en anglais, virgules, milliers a l'anglaise
qp = os.path.join(tmp, "gsc.csv")
with open(qp, "w", encoding="utf-8") as f:
	f.write('page,query,clicks,impressions\nhttps://www.exemple.fr/a/,"cafe, torrefaction",12,"1,234"\nhttps://exemple.fr/a,cafe vert,3,90\n')
q = r.load_queries(qp)
entry = q.get(r.page_key("https://exemple.fr/a"))
ok(entry and entry["clicks"] == 15 and entry["queries"][0] == (12, 1234, "cafe, torrefaction"), "export GSC anglais (virgules, 1,234)")

# --- fusion de bancs
fake = lambda name, rating, trust: {"pages": ["https://p/1"], "sites": ["p"], "repeat": 1, "results": {name: {
	"runs": [{"https://p/1": {"scores": dict.fromkeys(r.SCORE_KEYS, trust), "pq_rating": rating}}], "fails": 0,
	"secs": [3.0], "usage": {"calls": 1, "prompt_tokens": 100, "completion_tokens": 50, "cost": 0.001}}}}
for i, (n, rt, t) in enumerate([("ollama:a", "High", 8), ("openrouter:b", "Medium", 5), ("ollama:c", "High", 7)]):
	with open(os.path.join(tmp, f"b{i}.json"), "w", encoding="utf-8") as f:
		json.dump(fake(n, rt, t), f)
out = os.path.join(tmp, "merged")
proc = subprocess.run([sys.executable, os.path.join(repo, "bench.py"), "--merge",
	",".join(os.path.join(tmp, f"b{i}.json") for i in range(3)), "--out", out], capture_output=True, text=True, encoding="utf-8")
md = open(out + ".md", encoding="utf-8").read() if os.path.exists(out + ".md") else proc.stderr
ok("ollama:a" in md and "openrouter:b" in md and "consensus" in md, "bench --merge : trois bancs reunis, consensus calcule")
ok("1.00 $" in md, "bench : cout reel pour 1000 pages (0,001 $ par page = 1 $)")


# ====================== lecture d'une page : cas pieges ======================
filler = "<p>" + "Phrase de contenu sur le sujet traite par cette page de test. " * 40 + "</p>"
doc = ('<html><head><title>Vrai titre</title></head><body><header><svg><title>Menu</title></svg></header>'
	'<form id="aspnetForm" action="./"><input type="hidden" name="__VIEWSTATE"><main><h1>Simulateur</h1>' + filler
	+ '<table><tr><th>Four</th><th>Temp</th></tr><tr><td>Gaz</td><td>450</td></tr></table>'
	'<label>Poids</label><input type="number" id="poids"><select id="unite"><option>g</option></select>'
	'<img src="https://i0.wp.com/exemple.test/wp-content/photo-atelier.jpg" alt="Atelier">'
	'<img src="/img/logo-site.png" alt="logo"><a href="/x">lien jamais ferme <p>suite du texte hors du lien</p>'
	'<a href="/y">autre</a></main><input type="text" name="q"></form>'
	'<form class="search-form"><input type="search" name="s"><label>Rechercher sur le site</label></form></body></html>')
pg = r.parse("https://exemple.test/simulateur", doc)
ok(pg["title"] == "Vrai titre", "titre : le <title> d'une icone SVG n'est pas ajoute")
ok(pg["words"] > 300, "formulaire qui enveloppe toute la page (ASP.NET) : le contenu est lu")
ok(pg["tools"] == 1, "calculateur detecte par ses champs, pas par le formulaire enveloppe")
ok("| Gaz | 450" in pg["text"], "tableau : les cellules d'une ligne restent sur la meme ligne")
ok(pg["images"] == {"total": 1, "own": 1, "stock": 0, "alt": 1, "captions": 0}, "images : logo ecarte, CDN i0.wp.com compte comme le site")
ok("Rechercher sur le site" not in pg["text"], "formulaire de recherche ignore")
ok(pg["link_ratio"] < 0.1, "lien jamais ferme : la suite de la page n'est pas comptee comme un lien")
pg2 = r.parse("https://pixelshop.test/a", '<html><body><main>' + filler + '<img src="https://pixelshop.test/media/affiche.jpg" alt="Affiche"></main></body></html>')
ok(pg2["images"]["total"] == 1, "images : un domaine qui contient pixel ou logo ne les fait pas disparaitre")

# ====================== reponses du modele : libertes d'ecriture ======================
raw = {"scores": {"effort": "8/10", "originality": 7.6, "experience": "6", "expertise": 8, "authority": 5, "trust": "7,5", "needs_met": 9},
	"pq_rating": "HIGH", "ymyl": "High", "lowest_signals": ["Aucun", "Pas de transparence sur l'auteur d'un sujet de sante"],
	"fixes": "Ajouter une date", "evidence": None}
n = r.normalize(dict(raw))
ok(n["scores"]["effort"] == 8 and n["scores"]["trust"] == 8 and n["scores"]["originality"] == 8, "notes : 8/10, 7,5 et 7.6 compris")
ok(n["pq_rating"] == "High" and n["ymyl"] == "high", "casse : HIGH et High reconnus")
ok(n["lowest_signals"] == ["Pas de transparence sur l'auteur d'un sujet de sante"], "signal Lowest qui commence par Pas de : garde")
ok(n["fixes"] == ["Ajouter une date"] and n["evidence"] == [], "corrections et preuves toujours en liste")
ok(r.coherent(n)["pq_rating"] == "Lowest", "regle appliquee : signal Lowest sur YMYL high = Lowest")
try:
	r.normalize({"pq_rating": "High"})
	ok(False, "reponse sans notes refusee")
except ValueError:
	ok(True, "reponse sans notes refusee (pas de faux Low)")

# ====================== faux fournisseur d'IA local ======================
import http.server as hs, socketserver
GOOD = json.dumps({"page_purpose": "x", "inferred_query": "q", "ymyl": "none", "evidence": ["a -> b"], "lowest_signals": [],
	"scores": dict.fromkeys(r.SCORE_KEYS, 7), "pq_rating": "High", "fixes": [{"fix": "f", "why": "w"}], "verdict": "v"})
calls = []


class LLM(hs.BaseHTTPRequestHandler):
	def log_message(self, *a):
		pass

	def do_POST(self):
		body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
		calls.append(body)
		model, n_calls = body["model"], sum(1 for c in calls if c["model"] == body["model"])

		def send(code, payload):
			data = json.dumps(payload).encode()
			self.send_response(code)
			self.send_header("Content-Type", "application/json")
			self.send_header("Content-Length", str(len(data)))
			self.end_headers()
			self.wfile.write(data)
		answer = lambda content, finish="stop": send(200, {"choices": [{"message": {"content": content}, "finish_reason": finish}],
			"usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.001}})
		if model == "refuse-reflexion" and "reasoning_effort" in body:
			return send(400, {"error": {"message": "Unrecognized request argument supplied: reasoning_effort"}})
		if model == "refuse-tout" and any(k in body for k in r.OPTIONAL):
			return send(400, {"error": {"message": "Bad request"}})
		if model == "cle-refusee":
			return send(401, {"error": {"message": "Invalid API key"}})
		if model == "coupe" and n_calls == 1:
			return answer(GOOD[:60], "length")
		if model == "bavard":
			return answer("Bien sur, voici mon analyse de la page, sans JSON.")
		if model == "trop-long" and n_calls > 1:
			return send(400, {"error": {"message": "context length exceeded"}})
		answer("<think>je reflechis {pas du json}</think>" + GOOD if model == "pense" else GOOD)


class Threaded(socketserver.ThreadingMixIn, hs.HTTPServer):
	daemon_threads = True


llm = Threaded(("127.0.0.1", 0), LLM)
threading.Thread(target=llm.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{llm.server_port}/v1"
mk = lambda model: {"base": base, "model": model, "key": "k"}
count = lambda model: sum(1 for c in calls if c["model"] == model)

c1 = mk("refuse-reflexion")
out1 = r.chat(c1, "S", "U", 100)
ok(out1["pq_rating"] == "High" and c1["dropped"] == {"reasoning_effort"} and count("refuse-reflexion") == 2,
	"parametre refuse et nomme : lui seul est retire, le mode JSON est garde")
r.chat(c1, "S", "U", 100)
ok(count("refuse-reflexion") == 3, "parametre retire une fois pour toutes (pas de nouvel essai inutile)")
c2 = mk("refuse-tout")
r.chat(c2, "S", "U", 100)
ok(c2["dropped"] == set(r.OPTIONAL), "fournisseur minimal : les trois parametres optionnels retires, l'appel aboutit")
c3 = mk("coupe")
ok(r.chat(c3, "S", "U", 100)["pq_rating"] == "High" and calls[-1]["max_tokens"] == 160 and count("coupe") == 2,
	"reponse coupee : une seule relance avec plus de place")
try:
	r.chat(mk("bavard"), "S", "U", 100)
	ok(False, "reponse sans JSON")
except RuntimeError:
	ok(count("bavard") == 2, "reponse sans JSON : deux appels au plus, puis echec propre")
ok(r.chat(mk("pense"), "S", "U", 100)["pq_rating"] == "High", "reflexion entre balises <think> ignoree")
c4 = mk("trop-long")
r.chat(c4, "S", "U", 100)
try:
	r.chat(c4, "S", "U", 100)
	ok(False, "erreur 400 sans rapport avec les parametres")
except RuntimeError:
	ok(c4["dropped"] == set() and count("trop-long") == 2, "400 sans rapport (page trop longue) : aucun parametre sacrifie")
ok(c1["usage"]["calls"] == 2 and abs(c1["usage"]["cost"] - 0.002) < 1e-9, "consommation et cout reel cumules")
try:
	r.chat(mk("cle-refusee"), "S", "U", 100)
	ok(False, "cle refusee")
except r.Fatal:
	ok(r.STOP.is_set(), "cle refusee : arret general au lieu d'un echec par page")
try:
	r.chat(mk("ok"), "S", "U", 100)
	ok(False, "apres l'arret")
except r.Fatal:
	ok(count("ok") == 0, "apres l'arret : plus aucun appel envoye")
r.STOP.clear()

# ====================== sitemap coupe ou enorme ======================
site2 = tempfile.mkdtemp(prefix="qr-site2-")
with open(os.path.join(site2, "sitemap.xml"), "w", encoding="utf-8") as f:
	f.write('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
		+ "".join(f"<url><loc>http://HOST/p{i}.html</loc></url>" for i in range(1, 4)) + "<url><loc>http://HOST/coup")
for i in range(1, 4):
	with open(os.path.join(site2, f"p{i}.html"), "w", encoding="utf-8") as f:
		f.write(f"<html><head><title>Page {i}</title></head><body><main><h1>Page {i}</h1>{filler}</main></body></html>")
with open(os.path.join(site2, "index.html"), "w", encoding="utf-8") as f:
	f.write('<html><body><main><h1>Accueil</h1>' + filler + '<a href="/mentions-legales/">Mentions légales</a></main></body></html>')
srv2 = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(http.server.SimpleHTTPRequestHandler, directory=site2))
threading.Thread(target=srv2.serve_forever, daemon=True).start()
root2 = f"http://127.0.0.1:{srv2.server_port}/"
sm = open(os.path.join(site2, "sitemap.xml"), encoding="utf-8").read().replace("HOST", f"127.0.0.1:{srv2.server_port}")
open(os.path.join(site2, "sitemap.xml"), "w", encoding="utf-8").write(sm)
got = r.sitemap_urls(root2, "")
ok(len(got) == 3, "sitemap coupe en plein milieu : les adresses lisibles sont gardees")

# ====================== de bout en bout, en ligne de commande ======================
work = tempfile.mkdtemp(prefix="qr-run-")
common = ["--ai", "custom", "--base-url", base, "--model", "ok", "--key", "k", "--pause", "0"]
run = lambda *args: subprocess.run([sys.executable, os.path.join(repo, "rater.py"), *args, *common], capture_output=True,
	text=True, encoding="utf-8", cwd=work, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
p1 = run(root2, "--pages", "3", "--workers", "3", "--out", "seul")
ok(p1.returncode == 0 and os.path.exists(os.path.join(work, "seul.html")) and "Consommation : 4 appels" in p1.stdout,
	"un site, 3 pages en parallele : rapport ecrit, 3 notations + 1 synthese")
p2 = run(root2, "--pages", "3", "--out", "seul")
ok("(cache)" in p2.stdout and "4 reponses reprises du cache" in p2.stdout, "second passage : tout vient du cache, aucun appel")
with open(os.path.join(work, "sites.txt"), "w", encoding="utf-8") as f:
	f.write(f"{root2}\nhttp://localhost:{srv2.server_port}/\nhttp://127.0.0.1:9/  # site injoignable\n")
p3 = run("--sites", "sites.txt", "--pages", "2", "--workers", "3", "--out", "reseau")
files = sorted(os.listdir(os.path.join(work, "reseau"))) if os.path.isdir(os.path.join(work, "reseau")) else []
ok(p3.returncode == 0 and "index.html" in files and "reseau.csv" in files and "2 sites notes, 1 en echec" in p3.stdout,
	"reseau de 3 sites dont un injoignable : 2 notes, tableau d'ensemble ecrit")
p4 = subprocess.run([sys.executable, os.path.join(repo, "rater.py"), root2, "--pages", "2", "--no-cache", "--ai", "custom", "--base-url", base,
	"--model", "cle-refusee", "--key", "k", "--pause", "0"], capture_output=True, text=True, encoding="utf-8", cwd=work,
	env=dict(os.environ, PYTHONIOENCODING="utf-8"))
ok(p4.returncode != 0 and "Arret" in p4.stderr and count("cle-refusee") == 2, "cle refusee en ligne de commande : arret net, un seul appel de plus")
if "ECHEC" in "".join([]):
	pass
for proc in (p1, p3):
	if proc.returncode:
		print(proc.stdout[-1500:], proc.stderr[-1500:])
