"""Generate the 5 knowledge-graph presentation slides (EN + TH) as diagram-design HTML.

Usage: python gen_slides.py <out_dir>
"""
import sys, os, html, unicodedata

# ---- tokens (diagram-design default skin) ----
PAPER = "#f5f5f5"; PAPER2 = "#ececec"; INK = "#2d3142"; MUTED = "#4f5d75"; SOFT = "#5a6580"
ACCENT = "#bf4520"; ACCENT_TINT = "rgba(191,69,32,0.08)"; LINK = "#2e5aa8"
RULE = "rgba(45,49,66,0.12)"; RULE_SOLID = "#bfc0c0"

W, H = 1280, 720

KINDS = {
    "focal":    dict(fill=ACCENT_TINT, stroke=ACCENT, dash=None, tag=ACCENT),
    "backend":  dict(fill="#ffffff", stroke=INK, dash=None, tag=INK),
    "store":    dict(fill="rgba(45,49,66,0.05)", stroke=MUTED, dash=None, tag=MUTED),
    "input":    dict(fill="rgba(79,93,117,0.10)", stroke=SOFT, dash=None, tag=SOFT),
    "optional": dict(fill="rgba(45,49,66,0.02)", stroke="rgba(45,49,66,0.45)", dash="4,3", tag=SOFT),
}


class Slide:
    def __init__(self, lang, slug, eyebrow, title, desc):
        self.lang, self.slug = lang, slug
        self.eyebrow, self.title, self.desc = eyebrow, title, desc
        self.arrows, self.nodes, self.extra = [], [], []
        th = lang == "th"
        self.sans = "'Geist', 'Noto Sans Thai', system-ui, sans-serif" if th else "'Geist', system-ui, sans-serif"
        self.mono = "'Geist Mono', ui-monospace, monospace"
        self.serif = ("'Instrument Serif', 'Noto Serif Thai', serif" if th
                      else "'Instrument Serif', 'Noto Serif', serif")
        self.lh = 20 if th else 18  # sublabel line height (Thai needs room for marks)

    # ---- text helpers ----
    @staticmethod
    def has_thai(s):
        return any("฀" <= c <= "๿" for c in s)

    @staticmethod
    def width(s, size, mono=False):
        w = 0.0
        for c in s:
            if unicodedata.combining(c) or c in "ัิีึืฺุู็่้๊๋์ํ๎":
                continue
            w += 0.62 if mono and not ("฀" <= c <= "๿") else 0.60
        return w * size

    def sub_font(self, s):
        """Sublabels: mono for Latin, sans (register switch) for Thai prose."""
        return (self.sans, None) if self.has_thai(s) else (self.mono, None)

    def text(self, x, y, s, size, fam, fill=INK, weight=400, anchor="start", italic=False, spacing=None, upper=False):
        if upper and not self.has_thai(s):
            s = s.upper()
        attrs = f'x="{x}" y="{y}" fill="{fill}" font-size="{size}" font-family="{fam}"'
        if weight != 400:
            attrs += f' font-weight="{weight}"'
        if anchor != "start":
            attrs += f' text-anchor="{anchor}"'
        if italic:
            attrs += ' font-style="italic"'
        if spacing:
            attrs += f' letter-spacing="{spacing}"'
        return f"<text {attrs}>{html.escape(s)}</text>"

    # ---- primitives ----
    def node(self, x, y, w, h, kind, tag, name, subs=()):
        k = KINDS[kind]
        out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{PAPER}"/>']
        dash = f' stroke-dasharray="{k["dash"]}"' if k["dash"] else ""
        sw = 1.2 if kind == "focal" else 1
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{k["fill"]}" stroke="{k["stroke"]}" stroke-width="{sw}"{dash}/>')
        if tag:
            tw = int(self.width(tag, 8, mono=True) + len(tag) * 8 * 0.08 + 12 + 3) // 4 * 4 + 4
            out.append(f'<rect x="{x+12}" y="{y+12}" width="{tw}" height="16" rx="2" fill="none" stroke="{k["tag"]}" stroke-opacity="0.45" stroke-width="0.8"/>')
            out.append(self.text(x + 12 + tw / 2, y + 23, tag, 8, self.mono, fill=k["tag"], weight=500, anchor="middle", spacing="0.08em", upper=True))
        ny = y + 56 if tag else y + 32
        out.append(self.text(x + 16, ny, name, 16, self.sans, fill=INK, weight=600))
        self._check(name, 16, w - 28, False, f"{self.slug}: name '{name}'")
        for i, s in enumerate(subs):
            fam, _ = self.sub_font(s)
            mono = fam == self.mono
            out.append(self.text(x + 16, ny + 24 + i * self.lh, s, 12, fam, fill=MUTED))
            self._check(s, 12, w - 28, mono, f"{self.slug}: sub '{s}'")
        bottom = ny + 24 + (len(subs) - 1) * self.lh + 8 if subs else ny + 8
        if bottom > y + h:
            print(f"WARN {self.slug}: node '{name}' content overflows ({bottom} > {y+h})")
        self.nodes.append("\n".join(out))

    def _check(self, s, size, avail, mono, where):
        w = self.width(s, size, mono)
        if w > avail:
            print(f"WARN {where}: {w:.0f}px > {avail}px")

    def arrow(self, pts, style="muted", r=8):
        color = {"muted": MUTED, "accent": ACCENT, "link": LINK, "dashed": MUTED}[style]
        marker = {"muted": "arrow", "accent": "arrow-accent", "link": "arrow-link", "dashed": "arrow"}[style]
        d = f"M {pts[0][0]} {pts[0][1]}"
        for i in range(1, len(pts) - 1):
            (x0, y0), (x1, y1), (x2, y2) = pts[i - 1], pts[i], pts[i + 1]
            def toward(ax, ay, bx, by, dist):
                if ax == bx:
                    return ax, ay + (dist if by > ay else -dist)
                return ax + (dist if bx > ax else -dist), ay
            p1 = toward(x1, y1, x0, y0, r)
            p2 = toward(x1, y1, x2, y2, r)
            d += f" L {p1[0]} {p1[1]} Q {x1} {y1} {p2[0]} {p2[1]}"
        d += f" L {pts[-1][0]} {pts[-1][1]}"
        dash = ' stroke-dasharray="5,4"' if style == "dashed" else ""
        sw = 1.4 if style == "accent" else 1.2
        self.arrows.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}"{dash} marker-end="url(#{marker})"/>')

    def label(self, cx, cy, s, anchor="middle"):
        """Arrow label with opaque mask, centred at (cx, cy) (or left-aligned at cx)."""
        th = self.has_thai(s)
        size = 12
        fam = self.sans if th else self.mono
        tw = self.width(s if th else s.upper(), size, mono=not th) + (0 if th else len(s) * size * 0.06)
        mw = int(tw + 12 + 3) // 4 * 4
        mh = 20 if th else 16
        mx = cx - mw / 2 if anchor == "middle" else cx - 6
        self.arrows.append(f'<rect x="{mx:.0f}" y="{cy - mh/2:.0f}" width="{mw}" height="{mh}" rx="2" fill="{PAPER}"/>')
        tx = cx if anchor == "middle" else cx
        self.arrows.append(self.text(tx, cy + 4, s, size, fam, fill=SOFT, weight=500 if th else 400,
                                     anchor=anchor, spacing=None if th else "0.06em", upper=not th))

    def add(self, svg):
        self.extra.append(svg)

    def legend(self, items, y=668):
        out = [f'<line x1="48" y1="{y-20}" x2="{W-48}" y2="{y-20}" stroke="{RULE}" stroke-width="0.8"/>',
               self.text(48, y + 4, "LEGEND" if self.lang == "en" else "คำอธิบาย", 8 if self.lang == "en" else 12,
                         self.mono if self.lang == "en" else self.sans, fill=MUTED, weight=500,
                         spacing="0.14em" if self.lang == "en" else None)]
        x = 160
        for kind, txt in items:
            if kind in KINDS:
                k = KINDS[kind]
                dash = f' stroke-dasharray="{k["dash"]}"' if k["dash"] else ""
                out.append(f'<rect x="{x}" y="{y-8}" width="24" height="16" rx="3" fill="{k["fill"]}" stroke="{k["stroke"]}"{dash}/>')
            elif kind == "line":
                out.append(f'<line x1="{x}" y1="{y}" x2="{x+24}" y2="{y}" stroke="{MUTED}" stroke-width="1.2"/>')
            elif kind == "dline":
                out.append(f'<line x1="{x}" y1="{y}" x2="{x+24}" y2="{y}" stroke="{MUTED}" stroke-width="1.2" stroke-dasharray="5,4"/>')
            fam = self.sans
            out.append(self.text(x + 32, y + 4, txt, 12, fam, fill=MUTED))
            x += 32 + int(self.width(txt, 12)) + 40
        self.extra.append("\n".join(out))

    def callout(self, x, y, lines, size=20):
        for i, s in enumerate(lines):
            self.extra.append(self.text(x, y + i * (size + 8), s, size, self.serif, fill=MUTED, italic=self.lang == "en"))

    def render(self):
        th = self.lang == "th"
        fonts = ("https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@400;500;600"
                 "&family=Geist+Mono:wght@400;500;600&family=Noto+Serif:ital@0;1"
                 + ("&family=Noto+Sans+Thai:wght@400;500;600&family=Noto+Serif+Thai:wght@400" if th else "")
                 + "&display=swap")
        head = [self.text(48, 64, self.eyebrow, 12, self.mono if not self.has_thai(self.eyebrow) else self.sans,
                          fill=MUTED, weight=500, spacing=None if self.has_thai(self.eyebrow) else "0.16em",
                          upper=True),
                self.text(48, 112, self.title, 40, self.serif, fill=INK)]
        svg = f'''<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="{self.slug}-title {self.slug}-desc">
<title id="{self.slug}-title">{html.escape(self.title)}</title>
<desc id="{self.slug}-desc">{html.escape(self.desc)}</desc>
<defs>
<marker id="arrow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{MUTED}"/></marker>
<marker id="arrow-accent" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{ACCENT}"/></marker>
<marker id="arrow-link" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{LINK}"/></marker>
</defs>
<rect width="100%" height="100%" fill="{PAPER}"/>
{chr(10).join(head)}
{chr(10).join(self.arrows)}
{chr(10).join(self.nodes)}
{chr(10).join(self.extra)}
</svg>'''
        return f'''<!DOCTYPE html>
<html lang="{self.lang}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(self.title)}</title>
<link href="{fonts}" rel="stylesheet">
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: {self.sans}; background: {PAPER}; color: {INK}; min-height: 100vh;
  display: flex; align-items: center; justify-content: center; padding: 2rem; }}
.frame {{ max-width: 1280px; width: 100%; }}
.diagram-container {{ width: 100%; overflow-x: auto; }}
svg {{ width: 100%; min-width: 1280px; display: block; }}
@media print {{ .diagram-container {{ overflow-x: visible; }} svg {{ min-width: 0; }} }}
</style>
</head>
<body>
<div class="frame">
<div class="diagram-container">
{svg}
</div>
</div>
</body>
</html>
'''


def T(lang, en, th):
    return en if lang == "en" else th


# =====================================================================
# Slide 1 - overview
# =====================================================================
def slide1(L):
    s = Slide(L, f"kg-overview-{L}",
              T(L, "Knowledge graph · Overview", "Knowledge graph · ภาพรวม"),
              T(L, "From policy documents to a graph we can query",
                "จากเอกสารนโยบาย สู่กราฟความรู้ที่นำไปใช้งานได้"),
              T(L, "Documents are built into a Neo4j knowledge graph that powers impact analysis, question answering and quality checks.",
                "เอกสารถูกสร้างเป็นกราฟความรู้ใน Neo4j เพื่อใช้วิเคราะห์ผลกระทบ ตอบคำถาม และตรวจคุณภาพข้อมูล"))
    y, h = 300, 128
    # arrows
    s.arrow([(256, 364), (320, 364)]); s.label(288, 340, T(L, "in", "นำเข้า"))
    s.arrow([(560, 364), (624, 364)], "accent"); s.label(592, 340, T(L, "write", "บันทึก"))
    s.arrow([(864, 336), (912, 336), (912, 236), (968, 236)])
    s.arrow([(864, 364), (968, 364)])
    s.arrow([(864, 392), (912, 392), (912, 492), (968, 492)])
    # nodes
    s.node(48, y, 208, h, "input", T(L, "input", "INPUT"), T(L, "Policy documents", "เอกสารนโยบาย"),
           T(L, ["Thai / English Markdown", "new versions over time"],
             ["Markdown ไทย / อังกฤษ", "มีเวอร์ชันใหม่เรื่อย ๆ"]))
    s.node(320, y, 240, h, "backend", "build", T(L, "Build the graph", "สร้างกราฟ"),
           T(L, ["structure → references", "→ entities, layer by layer", "rules first, LLM if it helps"],
             ["โครงสร้าง → การอ้างอิง", "→ คำสำคัญ ทีละชั้น", "ใช้กฎก่อน ใช้ LLM เมื่อช่วยได้"]))
    s.node(624, y, 240, h, "focal", "neo4j", T(L, "Knowledge graph", "กราฟความรู้"),
           T(L, ["documents, versions, blocks", "entities, relationships", "every link cites its source"],
             ["เอกสาร · เวอร์ชัน · บล็อก", "คำสำคัญ · ความสัมพันธ์", "ทุกเส้นชี้กลับไปยังต้นทาง"]))
    s.node(968, 180, 264, 112, "focal", T(L, "use", "USE"), T(L, "Impact analysis", "วิเคราะห์ผลกระทบ"),
           T(L, ["new version → which blocks", "elsewhere need a review"],
             ["มีเวอร์ชันใหม่ → บล็อกไหน", "ในเอกสารอื่นต้องตรวจ"]))
    s.node(968, 308, 264, 112, "backend", None, T(L, "Q&A with citations", "ถาม-ตอบ พร้อมอ้างอิง"),
           T(L, ["answers point to exact blocks"], ["คำตอบชี้ถึงบล็อกต้นทาง"]))
    s.node(968, 436, 264, 112, "backend", None, T(L, "Store quality checks", "ตรวจคุณภาพข้อมูล"),
           T(L, ["missing references,", "conflicting values"],
             ["การอ้างอิงที่หาไม่พบ", "ค่าที่ขัดแย้งกัน"]))
    s.callout(48, 528, T(L, ["Cheap, precise signals first.", "The LLM only where it measurably helps."],
                         ["ใช้สัญญาณที่ถูกและแม่นยำก่อน", "ใช้ LLM เฉพาะจุดที่วัดผลแล้วว่าช่วยได้"]))
    s.legend([("input", T(L, "Input", "ข้อมูลเข้า")), ("backend", T(L, "Process / use", "ขั้นตอน / การใช้งาน")),
              ("focal", T(L, "Focus of this deck", "จุดสำคัญ"))])
    return s


# =====================================================================
# Slide 2 - build pipeline
# =====================================================================
def slide2(L):
    s = Slide(L, f"kg-build-{L}",
              T(L, "Part 1 · Build the graph", "ส่วนที่ 1 · สร้างกราฟ"),
              T(L, "Building the graph, one layer at a time", "สร้างกราฟทีละชั้น จากง่ายไปยาก"),
              T(L, "Five built steps turn documents into a stored graph; two LLM-based layers are planned.",
                "ห้าขั้นตอนที่สร้างแล้วเปลี่ยนเอกสารเป็นกราฟ และอีกสองชั้นที่ใช้ LLM อยู่ในแผน"))
    xs = [48, 292, 536, 780, 1024]
    w, y, h = 208, 184, 136
    cy = y + 68
    for a, b in zip(xs[:-1], xs[1:-1] + [xs[-1]]):
        s.arrow([(a + w, cy), (b, cy)], "accent" if b == 1024 else "muted")
    # planned branch: Entities -> Merge -> Dependencies -> Store
    s.arrow([(884, y + h), (884, 432)], "dashed")
    s.arrow([(984, 500), (1028, 500)], "dashed")
    s.arrow([(1128, 432), (1128, y + h)], "dashed")
    s.node(xs[0], y, w, h, "backend", "rules", T(L, "1  Identify", "1  ระบุเอกสาร"),
           T(L, ["which document is it?", "registry → similarity", "→ a person confirms"],
             ["ไฟล์นี้คือเอกสารใด", "ทะเบียน → ความคล้าย", "→ คนยืนยัน"]))
    s.node(xs[1], y, w, h, "backend", "rules · L0", T(L, "2  Structure", "2  โครงสร้าง"),
           T(L, ["document → version →", "section → block", "stable block IDs"],
             ["เอกสาร → เวอร์ชัน →", "หัวข้อ → บล็อก", "รหัสบล็อกคงที่"]))
    s.node(xs[2], y, w, h, "backend", "rules · L1", T(L, "3  References", "3  การอ้างอิง"),
           T(L, ["block cites a law or", "another document", "regex + registry"],
             ["บล็อกอ้างถึงกฎหมาย", "หรือเอกสารอื่น", "regex + ทะเบียนเอกสาร"]))
    s.node(xs[3], y, w, h, "backend", "rules · L2", T(L, "4  Entities", "4  คำสำคัญ"),
           T(L, ["concepts, roles, files", "+ values (10 days)", "registry rules, no NER"],
             ["แนวคิด บทบาท เอกสาร", "+ ค่า (เช่น 10 วัน)", "ใช้กฎจากทะเบียน"]))
    s.node(xs[4], y, w, h, "focal", "neo4j", T(L, "5  Store", "5  จัดเก็บ"),
           T(L, ["provenance on every edge", "vector index (e5)", "old links closed, kept"],
             ["ทุกเส้นมีที่มากำกับ", "ดัชนีเวกเตอร์ (e5)", "เส้นเก่าปิด ไม่ลบ"]))
    # planned row
    s.add(s.text(784, 592, T(L, "PLANNED · M6–M7", "อยู่ในแผน · M6–M7"), 12 if L == "th" else 8,
                 s.sans if L == "th" else s.mono, fill=SOFT, weight=500,
                 spacing=None if L == "th" else "0.16em"))
    s.node(784, 432, 200, 136, "optional", "llm · L3", T(L, "Merge duplicates", "รวมคำซ้ำ"),
           T(L, ["Thai ↔ English names", "embeddings + LLM", "reversible"],
             ["ชื่อไทย ↔ อังกฤษ", "embedding + LLM", "ย้อนกลับได้"]))
    s.node(1028, 432, 200, 136, "optional", "llm · L4", T(L, "Dependencies", "การพึ่งพา"),
           T(L, ["uses a fact without", "citing it; LLM must", "quote evidence"],
             ["ใช้ข้อเท็จจริงโดยไม่อ้าง", "LLM ต้องยกหลักฐาน", "จากข้อความจริง"]))
    s.callout(48, 464, T(L, ["Steps 1–5 are built and run", "without an LLM today."],
                         ["ขั้นตอนที่ 1–5 สร้างเสร็จแล้ว", "และยังไม่ต้องใช้ LLM"]))
    s.add(s.text(48, 536, T(L, "LLM is added only where a test shows it helps;", "จะเพิ่ม LLM เฉพาะจุดที่ทดสอบแล้วว่าช่วยได้"),
                 14, s.sans, fill=MUTED))
    s.add(s.text(48, 558, T(L, "an LLM fallback for entities was tested, not adopted.", "LLM สำหรับคำสำคัญทดสอบแล้ว ยังไม่นำมาใช้"),
                 14, s.sans, fill=MUTED))
    s.legend([("backend", T(L, "Built · rules", "สร้างแล้ว · ใช้กฎ")), ("focal", T(L, "Graph store", "ที่เก็บกราฟ")),
              ("optional", T(L, "Planned · uses LLM", "อยู่ในแผน · ใช้ LLM"))])
    return s


# =====================================================================
# Slide 3 - graph model + example
# =====================================================================
def slide3(L):
    s = Slide(L, f"kg-model-{L}",
              T(L, "What the graph contains", "ในกราฟมีอะไรบ้าง"),
              T(L, "Blocks, the names they mention, and what they cite",
                "บล็อก คำสำคัญที่กล่าวถึง และสิ่งที่อ้างอิง"),
              T(L, "Data model of documents, versions, sections, blocks, entities and aliases, with an annual-leave example.",
                "โมเดลข้อมูลของเอกสาร เวอร์ชัน หัวข้อ บล็อก คำสำคัญ และชื่อเรียก พร้อมตัวอย่างวันลาพักร้อน"))
    # arrows
    s.arrow([(140, 240), (140, 296)]); s.label(150, 268, "HAS_VERSION", anchor="start")
    s.arrow([(140, 368), (140, 424)]); s.label(150, 396, "CONTAINS", anchor="start")
    s.arrow([(232, 468), (312, 468)]); s.label(272, 444, "CONTAINS")
    s.arrow([(392, 424), (392, 204), (232, 204)], "link"); s.label(402, 300, "REFERENCES", anchor="start")
    s.arrow([(512, 468), (600, 468)], "accent"); s.label(556, 444, "MENTIONS")
    s.arrow([(688, 240), (688, 424)]); s.label(698, 332, "ALIAS_OF", anchor="start")
    s.arrow([(432, 512), (432, 576), (480, 576), (480, 512)], "dashed")
    s.label(456, 600, T(L, "DEPENDS · planned", "DEPENDS · อยู่ในแผน"))
    # nodes
    s.node(48, 168, 184, 72, "backend", None, T(L, "Document", "เอกสาร"), T(L, ["e.g. HR Policy"], ["เช่น นโยบาย HR"]))
    s.node(48, 296, 184, 72, "store", None, T(L, "Version", "เวอร์ชัน"), T(L, ["one uploaded file"], ["ไฟล์ที่อัปโหลด"]))
    s.node(48, 424, 184, 88, "store", None, T(L, "Section", "หัวข้อ"), T(L, ["a heading"], ["หัวเรื่องในไฟล์"]))
    s.node(312, 424, 200, 88, "focal", None, T(L, "Block", "บล็อก"), T(L, ["paragraph, table, list"], ["ย่อหน้า ตาราง รายการ"]))
    s.node(600, 424, 176, 88, "backend", None, T(L, "Entity", "คำสำคัญ"), T(L, ["concept, role,", "artifact"], ["แนวคิด บทบาท", "ชิ้นงาน"]))
    s.node(600, 168, 176, 72, "input", None, T(L, "Alias", "ชื่อเรียก"), T(L, ["Thai / English name"], ["ชื่อไทยหรืออังกฤษ"]))
    # example panel
    px, pw = 840, 392
    s.add(f'<rect x="{px}" y="152" width="{pw}" height="460" rx="6" fill="#ffffff" stroke="{RULE_SOLID}" stroke-width="1"/>')
    s.add(s.text(px + 20, 184, T(L, "EXAMPLE · LEAVE 10 → 12 DAYS", "ตัวอย่าง · วันลา 10 → 12 วัน"),
                 12, s.mono if L == "en" else s.sans, fill=ACCENT, weight=500, spacing="0.12em" if L == "en" else None))
    s.add(s.text(px + 20, 212, T(L, "HR Policy v4 edits block A-12:", "นโยบาย HR v4 แก้บล็อก A-12:"), 14, s.sans, fill=INK))
    s.add(s.text(px + 20, 234, T(L, "“Annual leave is 10 days a year.”", "“ลาพักร้อนได้ปีละ 10 วัน”"), 14, s.sans, fill=MUTED, italic=L == "en"))
    rows = [
        (T(L, "Onboarding guide", "คู่มือพนักงานใหม่"), T(L, "“For leave rules, see the HR Policy.”", "“ดูกฎการลาในนโยบาย HR”"),
         T(L, "found via REFERENCES", "พบผ่าน REFERENCES"), INK),
        (T(L, "Staff FAQ (Thai)", "FAQ พนักงาน"), "“พนักงานลาพักร้อนได้ 10 วัน”",
         T(L, "found via the value 10 days", "พบผ่านค่า 10 วัน บน MENTIONS"), INK),
        (T(L, "Budget guide", "คู่มืองบประมาณ"), T(L, "“budget = headcount × leave days”", "“งบ = จำนวนคน × วันลา”"),
         T(L, "needs DEPENDS · planned", "ต้องใช้ DEPENDS · อยู่ในแผน"), SOFT),
    ]
    yy = 264
    for name, quote, how, col in rows:
        s.add(f'<line x1="{px+20}" y1="{yy}" x2="{px+pw-20}" y2="{yy}" stroke="{RULE}" stroke-width="0.8"/>')
        s.add(s.text(px + 20, yy + 30, name, 16, s.sans, fill=INK, weight=600))
        s.add(s.text(px + 20, yy + 54, quote, 14, s.sans, fill=MUTED))
        mark = "✓ " if col == INK else "○ "
        s.add(s.text(px + 20, yy + 80, mark + how, 14, s.sans, fill=ACCENT if col == INK else SOFT, weight=500))
        yy += 108
    s.legend([("line", T(L, "Built", "สร้างแล้ว")), ("dline", T(L, "Planned", "อยู่ในแผน")),
              ("focal", T(L, "Block = unit of change", "บล็อก = หน่วยที่เปลี่ยนแปลง"))])
    return s


# =====================================================================
# Slide 4 - impact analysis
# =====================================================================
def slide4(L):
    s = Slide(L, f"kg-impact-{L}",
              T(L, "Part 2 · Use the graph", "ส่วนที่ 2 · ใช้งานกราฟ"),
              T(L, "A new version arrives: what else must change?",
                "มีเวอร์ชันใหม่: เอกสารส่วนไหนต้องแก้ตาม"),
              T(L, "Impact analysis in eight steps, from upload and diff through graph-based candidate search to human review.",
                "การวิเคราะห์ผลกระทบแปดขั้นตอน ตั้งแต่อัปโหลด เทียบความต่าง ค้นหาผ่านกราฟ จนถึงคนตรวจทาน"))
    xs = [48, 352, 656, 960]
    w, h = 272, 148
    y1, y2 = 168, 408
    c1, c2 = y1 + 74, y2 + 74
    for a, b in zip(xs[:-1], xs[1:]):
        s.arrow([(a + w, c1), (b, c1)])
    s.arrow([(1096, y1 + h), (1096, y2)], "accent")
    s.label(1106, (y1 + h + y2) // 2, T(L, "candidates", "บล็อกที่อาจกระทบ"), anchor="start")
    s.arrow([(960, c2), (656 + w, c2)])
    s.arrow([(656, c2), (352 + w, c2)])
    s.arrow([(352, c2), (48 + w, c2)], "dashed")
    s.node(xs[0], y1, w, h, "backend", "8 · done", T(L, "Upload & identify", "อัปโหลด และระบุเอกสาร"),
           T(L, ["new file → which document?", "new version supersedes old"],
             ["ไฟล์ใหม่คือเอกสารใด", "เวอร์ชันใหม่แทนเวอร์ชันเก่า"]))
    s.node(xs[1], y1, w, h, "backend", "9 · done", T(L, "Match & diff", "เทียบความต่าง"),
           T(L, ["old vs new blocks:", "same / edited / moved", "/ removed / added"],
             ["จับคู่บล็อกเก่ากับใหม่", "เหมือนเดิม / แก้ / ย้าย", "/ ลบ / เพิ่ม"]))
    s.node(xs[2], y1, w, h, "backend", "10 · done", T(L, "Light update", "อัปเดตเบื้องต้น"),
           T(L, ["references, entities and", "vectors for new blocks"],
             ["สร้างการอ้างอิง คำสำคัญ", "และเวกเตอร์ให้บล็อกใหม่"]))
    s.node(xs[3], y1, w, h, "focal", "11 · done", T(L, "Find candidates", "หาบล็อกที่อาจกระทบ"),
           T(L, ["graph: cites it, states the", "old value, shares an entity", "+ text & vector search"],
             ["กราฟ: อ้างถึง, ระบุค่าเดิม,", "มีคำสำคัญร่วมกัน", "+ ค้นข้อความและเวกเตอร์"]))
    s.node(xs[3], y2, w, h, "backend", "12 · done", T(L, "Rank", "จัดอันดับ"),
           T(L, ["graph signals first,", "then search score"],
             ["สัญญาณจากกราฟก่อน", "แล้วจึงคะแนนการค้นหา"]))
    s.node(xs[2], y2, w, h, "backend", "13 · testing", T(L, "LLM check", "LLM ตรวจสอบ"),
           T(L, ["needs update / not affected", "/ unsure + quoted reason"],
             ["ต้องแก้ / ไม่กระทบ / ไม่แน่ใจ", "พร้อมเหตุผลและหลักฐาน"]))
    s.node(xs[1], y2, w, h, "backend", "14 · partly", T(L, "Report & review", "รายงาน และคนตรวจ"),
           T(L, ["CSV of blocks to check;", "a person approves / rejects"],
             ["CSV รายการบล็อกที่ต้องดู", "คนอนุมัติ / ปฏิเสธ"]))
    s.node(xs[0], y2, w, h, "optional", "15 · planned", T(L, "Full update", "อัปเดตเต็มรูปแบบ"),
           T(L, ["merge entities, dependencies", "close old links (M6–M7)"],
             ["รวมคำซ้ำ และการพึ่งพา", "ปิดเส้นเก่า (M6–M7)"]))
    s.callout(48, 610, T(L, ["Graph-first ranking: 66% of affected blocks in the top 5, vs 28% for text search alone."],
                         ["จัดอันดับด้วยกราฟก่อน: พบบล็อกที่กระทบ 66% ใน 5 อันดับแรก เทียบกับ 28% เมื่อค้นข้อความอย่างเดียว"]),
              size=18)
    s.add(s.text(48, 634, T(L, "Recall@5 on the AI-labelled change test set; not yet checked by a person.",
                            "Recall@5 บนชุดทดสอบที่ AI ติดป้าย ยังไม่ได้ให้คนตรวจ"), 11, s.sans, fill=SOFT))
    s.legend([("backend", T(L, "Step", "ขั้นตอน")), ("focal", T(L, "Where the graph pays off", "จุดที่กราฟช่วยมากที่สุด")),
              ("optional", T(L, "Planned", "อยู่ในแผน"))])
    return s


# =====================================================================
# Slide 5 - status & roadmap
# =====================================================================
def slide5(L):
    s = Slide(L, f"kg-roadmap-{L}",
              T(L, "Status · 26 Nov 2026", "สถานะ · 26 พ.ย. 2026"),
              T(L, "Where we are, and what comes next", "ตอนนี้อยู่ตรงไหน และขั้นต่อไป"),
              T(L, "Milestones M0 to M7: structure, diff, references and entities built; impact analysis in progress; entity merge and dependencies planned.",
                "เป้าหมาย M0 ถึง M7: โครงสร้าง การเทียบ การอ้างอิง และคำสำคัญสร้างแล้ว การวิเคราะห์ผลกระทบกำลังทำ การรวมคำซ้ำและการพึ่งพาอยู่ในแผน"))
    ms = [
        ("M0", T(L, "Setup", "ตั้งค่าระบบ"), T(L, ["done"], ["เสร็จ"]), "done"),
        ("M1", T(L, "Structure", "โครงสร้าง"), T(L, ["done"], ["เสร็จ"]), "done"),
        ("M2", T(L, "Version diff", "เทียบเวอร์ชัน"), T(L, ["built ·", "needs human check"], ["สร้างแล้ว", "รอคนตรวจ"]), "done"),
        ("M3", T(L, "References", "การอ้างอิง"), T(L, ["built ·", "needs human check"], ["สร้างแล้ว", "รอคนตรวจ"]), "done"),
        ("M4", T(L, "Entities", "คำสำคัญ"), T(L, ["done"], ["เสร็จ"]), "done"),
        ("M5", T(L, "Impact analysis", "วิเคราะห์ผลกระทบ"), T(L, ["in progress ·", "steps 1–2 done"], ["กำลังทำ", "ขั้น 1–2 เสร็จ"]), "now"),
        ("M6", T(L, "Merge entities", "รวมคำซ้ำ"), T(L, ["planned"], ["อยู่ในแผน"]), "plan"),
        ("M7", T(L, "Dependencies", "การพึ่งพา"), T(L, ["planned"], ["อยู่ในแผน"]), "plan"),
    ]
    step = 148
    xs = [48 + 74 + step * i for i in range(8)]
    ly = 200
    s.add(f'<line x1="{xs[0]}" y1="{ly}" x2="{xs[5]}" y2="{ly}" stroke="{INK}" stroke-width="1.6"/>')
    s.add(f'<line x1="{xs[5]}" y1="{ly}" x2="{xs[7]}" y2="{ly}" stroke="{MUTED}" stroke-width="1.2" stroke-dasharray="5,4"/>')
    for x, (code, name, subs, st) in zip(xs, ms):
        if st == "done":
            s.add(f'<circle cx="{x}" cy="{ly}" r="7" fill="{INK}"/>')
        elif st == "now":
            s.add(f'<circle cx="{x}" cy="{ly}" r="11" fill="{PAPER}" stroke="{ACCENT}" stroke-width="1.6"/>')
            s.add(f'<circle cx="{x}" cy="{ly}" r="6" fill="{ACCENT}"/>')
        else:
            s.add(f'<circle cx="{x}" cy="{ly}" r="7" fill="{PAPER}" stroke="{MUTED}" stroke-width="1.2"/>')
        col = ACCENT if st == "now" else (INK if st == "done" else SOFT)
        s.add(s.text(x, ly - 24, code, 12, s.mono, fill=col, weight=500, anchor="middle", spacing="0.08em"))
        s.add(s.text(x, ly + 40, name, 16, s.sans, fill=INK if st != "plan" else SOFT, weight=600, anchor="middle"))
        s._check(name, 16, step - 12, False, f"{s.slug}: ms '{name}'")
        for i, t in enumerate(subs):
            fam = s.sans if s.has_thai(t) else s.mono
            s.add(s.text(x, ly + 62 + i * s.lh, t, 12, fam, fill=col if st == "now" else MUTED, anchor="middle"))
            s._check(t, 12, step - 12, fam == s.mono, f"{s.slug}: ms sub '{t}'")
    # two cards
    cards = [
        (48, 584, T(L, "RESULTS SO FAR · AI LABELS", "ผลลัพธ์ตอนนี้ · ป้ายจาก AI"), [
            T(L, "References (L1): precision 0.94, recall 0.94", "การอ้างอิง (L1): precision 0.94, recall 0.94"),
            T(L, "Version diff: agrees on 29 of 30 sampled blocks", "เทียบเวอร์ชัน: ตรงกัน 29 จาก 30 บล็อกตัวอย่าง"),
            T(L, "Impact, top 5: 66% graph-first vs 28% search", "ผลกระทบ 5 อันดับแรก: กราฟ 66% เทียบค้นหา 28%"),
        ], False),
        (656, 576, T(L, "NEEDED BEFORE REAL USE", "ต้องมีก่อนใช้งานจริง"), [
            T(L, "Human labels on a blind sample (today: AI labels)", "ให้คนติดป้ายตัวอย่างแบบ blind (ตอนนี้ใช้ป้ายจาก AI)"),
            T(L, "Access rights applied to every query", "ใช้สิทธิ์การเข้าถึงกับทุกการค้นหา"),
            T(L, "Human review loop + scheduled backups", "ขั้นตอนคนตรวจ + สำรองข้อมูลตามรอบ"),
        ], True),
    ]
    for cx, cw, head, lines, focal in cards:
        cy = 340
        s.add(f'<rect x="{cx}" y="{cy}" width="{cw}" height="232" rx="6" fill="#ffffff" stroke="{ACCENT if focal else RULE_SOLID}" stroke-width="{1.2 if focal else 1}"/>')
        s.add(s.text(cx + 24, cy + 40, head, 12, s.mono if L == "en" else s.sans, fill=ACCENT if focal else MUTED,
                     weight=500, spacing="0.12em" if L == "en" else None))
        for i, t in enumerate(lines):
            s.add(s.text(cx + 24, cy + 92 + i * 52, t, 16, s.sans, fill=INK))
            s._check(t, 16, cw - 48, False, f"{s.slug}: card '{t}'")
    s.legend([("line", T(L, "Done / built", "เสร็จ / สร้างแล้ว")), ("dline", T(L, "Planned", "อยู่ในแผน")),
              ("focal", T(L, "Current milestone", "งานปัจจุบัน"))])
    return s


SLIDES = [("01_overview", slide1), ("02_build", slide2), ("03_graph_model", slide3),
          ("04_impact", slide4), ("05_roadmap", slide5)]

if __name__ == "__main__":
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    for name, fn in SLIDES:
        for L in ("en", "th"):
            s = fn(L)
            p = os.path.join(out, f"{name}_{L.upper()}.html")
            with open(p, "w", encoding="utf-8") as f:
                f.write(s.render())
            print("wrote", p)
