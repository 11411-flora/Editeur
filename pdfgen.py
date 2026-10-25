from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


def fabriquer_pdf(titre, texte):
    """Fabrique un PDF simple : le titre, puis le texte ligne par ligne."""
    tampon = BytesIO()
    pdf = SimpleDocTemplate(tampon, pagesize=A4, title=titre)
    styles = getSampleStyleSheet()
    elements = [Paragraph(escape(titre), styles["Title"]), Spacer(1, 12)]
    for ligne in (texte or "(document vide)").split("\n"):
        elements.append(Paragraph(escape(ligne) or "&nbsp;", styles["BodyText"]))
    pdf.build(elements)
    return tampon.getvalue()
