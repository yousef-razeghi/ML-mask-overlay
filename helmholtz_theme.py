"""
helmholtz_theme.py
------------------
Central place for the Helmholtz corporate look used across the cropper app.

Anchored on the Helmholtz corporate blue (#005AA0) with a darker shade for
headers and a light tint for surfaces. Kept deliberately small and dependency
free so it works unchanged inside NOMAD NORTH / Voila.
"""
import ipywidgets as widgets
from IPython.display import HTML

# --- Palette -------------------------------------------------------------- #
HZ_BLUE        = "#005AA0"   # Helmholtz primary blue
HZ_BLUE_DARK   = "#002F5E"   # deep blue (headers, titles)
HZ_BLUE_LIGHT  = "#8CB7DA"   # light blue (borders, accents)
HZ_TINT        = "#EAF2F9"   # very light blue surface
HZ_CYAN        = "#009FE3"   # bright secondary blue (links / focus)
HZ_GREEN       = "#2E7D32"   # success
HZ_AMBER       = "#B25900"   # warning
HZ_RED         = "#C62828"   # error
HZ_TEXT        = "#1A2A3A"   # body text
HZ_MUTED       = "#5B6B7B"   # secondary text
HZ_SURFACE     = "#FFFFFF"   # cards
HZ_BORDER      = "#D5DEE7"   # neutral border

FONT = "Arial, Helvetica, sans-serif"


def global_css():
    """Page-level CSS. Display once at the top of the notebook."""
    return HTML(f"""
<style>
  :root {{
    --hz-blue: {HZ_BLUE};
    --hz-blue-dark: {HZ_BLUE_DARK};
    --hz-tint: {HZ_TINT};
    --hz-border: {HZ_BORDER};
  }}
  .hz-app, .hz-app * {{ font-family: {FONT}; }}
  /* Tidy, on-brand ipywidgets buttons */
  .hz-app .jupyter-button {{ border-radius: 4px; font-weight: 600; }}
  .hz-app .widget-button.mod-primary,
  .hz-app .jupyter-button.mod-primary {{
      background-color: {HZ_BLUE} !important; color: #fff !important;
  }}
  .hz-app .widget-button.mod-success,
  .hz-app .jupyter-button.mod-success {{
      background-color: {HZ_GREEN} !important; color: #fff !important;
  }}
  /* Selection / dropdown focus tint */
  .hz-app .widget-select select:focus,
  .hz-app .widget-dropdown select:focus,
  .hz-app .widget-text input:focus {{
      outline: 2px solid {HZ_CYAN}; outline-offset: 0;
  }}
  /* Hide ipyvuetify file-input chips if that widget ever appears */
  .v-chip {{ display: none !important; }}
  .v-file-input__text {{ display: none !important; }}
</style>
""")


def header(title, subtitle=""):
    """Helmholtz-blue banner widget."""
    sub = (f"<div style='font-size:13px;color:#D7E6F2;margin-top:2px;'>{subtitle}</div>"
           if subtitle else "")
    html = (
        f"<div style='background:linear-gradient(90deg,{HZ_BLUE_DARK},{HZ_BLUE});"
        f"padding:14px 20px;border-radius:6px;color:#fff;'>"
        f"<div style='font-size:20px;font-weight:700;letter-spacing:.01em;'>{title}</div>"
        f"{sub}</div>"
    )
    return widgets.HTML(html)


def step_label(number, text):
    """Compact numbered section heading."""
    html = (
        f"<div style='display:flex;align-items:center;gap:8px;margin:2px 0 6px 0;'>"
        f"<span style='background:{HZ_BLUE};color:#fff;width:22px;height:22px;"
        f"border-radius:50%;display:inline-flex;align-items:center;justify-content:center;"
        f"font-size:13px;font-weight:700;'>{number}</span>"
        f"<span style='font-size:15px;font-weight:700;color:{HZ_BLUE_DARK};'>{text}</span>"
        f"</div>"
    )
    return widgets.HTML(html)


def card(children, padding="12px 14px"):
    """Light surface container with a subtle border."""
    return widgets.VBox(
        children,
        layout=widgets.Layout(
            border=f"1px solid {HZ_BORDER}",
            border_radius="6px",
            padding=padding,
            margin="6px 0",
            background_color=HZ_SURFACE,
            width="100%",
        ),
    )


def hint(text):
    """Muted helper text."""
    return widgets.HTML(
        f"<div style='font-size:12px;color:{HZ_MUTED};font-style:italic;'>{text}</div>"
    )
