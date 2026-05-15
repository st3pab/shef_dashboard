import dash
from dash import dcc, html, Input, Output, State, callback_context
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime
import json
import os
from difflib import SequenceMatcher
import base64
import io
import pdfplumber
import re

# Подавляем вывод pandas и других библиотек
import warnings

warnings.filterwarnings("ignore")

# Перенаправляем вывод в null для подавления логов загрузки
import sys
import contextlib

# Сохраняем оригинальный stdout
original_stdout = sys.stdout


# Функция для временного отключения вывода
@contextlib.contextmanager
def suppress_output():
    with open(os.devnull, 'w') as devnull:
        sys.stdout = devnull
        try:
            yield
        finally:
            sys.stdout = original_stdout


# Загрузка данных без вывода в консоль
with suppress_output():
    df_raw = pd.read_csv("data/farmers_sku.csv")
    try:
        df_seasonal_products = pd.read_csv("data/seasonal_products.csv", encoding='utf-8-sig')
    except:
        df_seasonal_products = pd.DataFrame()

SEASON_CACHE = {}
CATEGORY_CACHE = {}
PRICE_TIMELINE_CACHE = {}


def get_season_fast(product_name):
    if product_name in SEASON_CACHE:
        return SEASON_CACHE[product_name]
    name_lower = product_name.lower()
    rules = [
        (['клубник', 'земляник'], (5, 8, "Ягодный сезон", "Сезон клубники")),
        (['малин'], (6, 8, "Ягодный сезон", "Ароматная малина")),
        (['смородин'], (7, 8, "Ягодный сезон", "Витаминная бомба")),
        (['яблок'], (8, 10, "Фруктовый сезон", "Сочные яблоки")),
        (['груш'], (8, 9, "Фруктовый сезон", "Медовые груши")),
        (['тыкв'], (9, 11, "Осенний урожай", "Тыква - королева осени")),
        (['кабачк'], (6, 8, "Летний сезон", "Нежные кабачки")),
        (['огурц'], (6, 8, "Летний сезон", "Хрустящие огурцы")),
        (['помидор', 'томат'], (7, 9, "Летний сезон", "Сладкие помидоры")),
        (['баклажан'], (7, 9, "Летний сезон", "Икра заморская")),
        (['перец'], (7, 9, "Летний сезон", "Сочный болгарский перец")),
        (['базилик'], (6, 8, "Зелень", "Ароматный базилик")),
        (['укроп', 'петрушк'], (5, 9, "Зелень", "Свежая зелень")),
        (['салат'], (5, 9, "Зелень", "Листовой салат")),
        (['щавел'], (4, 6, "Весенний сезон", "Щавель для супа")),
        (['редис'], (5, 6, "Весенний сезон", "Хрустящий редис")),
        (['чай', 'сбор', 'уксус'], (1, 12, "Круглый год", "Доступен всегда")),
    ]
    for keywords, season in rules:
        if any(kw in name_lower for kw in keywords):
            SEASON_CACHE[product_name] = season
            return season
    SEASON_CACHE[product_name] = (1, 12, "Круглый год", "Доступен всегда")
    return (1, 12, "Круглый год", "Доступен всегда")


def get_category_fast(product_name):
    if product_name in CATEGORY_CACHE:
        return CATEGORY_CACHE[product_name]
    name_lower = product_name.lower()
    categories = {
        'Ягоды': ['клубник', 'малин', 'смородин', 'земляник', 'ежевик'],
        'Фрукты': ['яблок', 'груш', 'слив', 'абрикос'],
        'Овощи': ['тыкв', 'кабачк', 'огурц', 'помидор', 'томат', 'баклажан', 'перец', 'редис', 'картофел', 'морков',
                  'свёкл', 'капуст', 'лук'],
        'Зелень': ['укроп', 'петрушк', 'салат', 'щавел', 'базилик', 'кинз'],
        'Бакалея': ['уксус', 'чай', 'сбор', 'мед', 'варенье', 'соус'],
    }
    for category, keywords in categories.items():
        if any(kw in name_lower for kw in keywords):
            CATEGORY_CACHE[product_name] = category
            return category
    CATEGORY_CACHE[product_name] = 'Другое'
    return 'Другое'


def is_premium_fast(product_name, description):
    text = f"{product_name} {description}".lower()
    premium_keywords = ['премиум', 'organic', 'элитный', 'handmade', 'био', 'эко']
    return any(kw in text for kw in premium_keywords)


def is_rare_fast(product_name, description):
    text = f"{product_name} {description}".lower()
    rare_keywords = ['редкий', 'уникальный', 'авторский', 'ручной сбор']
    return any(kw in text for kw in rare_keywords)


def generate_price_timeline(product_name, base_price):
    cache_key = f"{product_name}_{base_price}"
    if cache_key in PRICE_TIMELINE_CACHE:
        return PRICE_TIMELINE_CACHE[cache_key]
    season_start, season_end, _, _ = get_season_fast(product_name)
    months = ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']
    prices = []
    for month in range(1, 13):
        if season_start <= month <= season_end:
            factor = 0.6
        elif month < season_start:
            factor = 1.15 + (season_start - month) * 0.04
        else:
            factor = 1.35 + (month - season_end) * 0.04
        price = base_price * min(factor, 2.0)
        prices.append(round(price, 0))
    return months, prices


def similarity_score(a, b):
    if not a or not b:
        return 0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def fuzzy_search(query, products_list, limit=50):
    if not query or len(query) < 2:
        return []
    query_lower = query.lower().strip()
    results = []
    for product in products_list:
        product_name = product.get('product_original', '').lower()
        category = product.get('category', '').lower()
        farmer = product.get('farmer', '').lower()
        score = max(
            similarity_score(query_lower, product_name) * 1.0,
            similarity_score(query_lower, category) * 0.7,
            similarity_score(query_lower, farmer) * 0.5
        )
        if query_lower in product_name:
            score = max(score, 0.8)
        if score > 0.25:
            results.append((score, product['id']))
    results.sort(key=lambda x: x[0], reverse=True)
    return [x[1] for x in results[:limit]]


def get_current_season():
    month = datetime.now().month
    if month in [12, 1, 2]:
        return "зима"
    elif month in [3, 4, 5]:
        return "весна"
    elif month in [6, 7, 8]:
        return "лето"
    else:
        return "осень"


# Обработка продуктов без вывода
with suppress_output():
    products_list = []
    all_categories = set()
    for idx, row in df_raw.iterrows():
        product_name = row.get('name_product', f"Продукт_{idx}")
        if pd.isna(product_name):
            continue
        season_start, season_end, season_group, season_tip = get_season_fast(product_name)
        category = get_category_fast(product_name)
        premium = is_premium_fast(product_name, row.get('product_description', ''))
        rare = is_rare_fast(product_name, row.get('product_description', ''))
        region = str(row.get('region', 'Россия'))[:20]
        all_categories.add(category)
        base_prices = {'Ягоды': 450, 'Фрукты': 180, 'Овощи': 120, 'Зелень': 250, 'Бакалея': 350, 'Другое': 200}
        base_price = base_prices.get(category, 200)
        if premium:
            base_price = int(base_price * 1.6)
        if rare:
            base_price = int(base_price * 1.3)
        months, price_timeline = generate_price_timeline(product_name, base_price)
        current_month = datetime.now().month
        if season_start <= current_month <= season_end:
            status = "В сезоне"
            status_color = "#FFF3E0"
            status_text_color = "#E0A32E"
        elif current_month < season_start:
            status = "Скоро"
            status_color = "#E9ECEF"
            status_text_color = "#6C757D"
        else:
            status = "Не сезон"
            status_color = "#E9ECEF"
            status_text_color = "#6C757D"
        product_data = {
            "id": idx, "product": str(product_name).lower(), "product_original": str(product_name)[:60],
            "category": category, "season_tip": season_tip, "status": status,
            "status_color": status_color, "status_text_color": status_text_color,
            "farmer": str(row.get('shop_name', 'Фермер'))[:35], "region": region,
            "premium": premium, "rare": rare, "current_price": price_timeline[current_month - 1],
            "price_timeline": price_timeline, "months": months,
            "url": str(row.get('url_product', '#')), "farmer_url": str(row.get('url_farmer', '#'))
        }
        products_list.append(product_data)

products_db = pd.DataFrame(products_list)
categories_list = sorted([c for c in all_categories if c and c != 'nan'])

FAVORITES_FILE = "favorites.json"
favorites = json.load(open(FAVORITES_FILE)) if os.path.exists(FAVORITES_FILE) else []

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], title="Своё Шеф",
                suppress_callback_exceptions=True)

app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;500;600;700;800&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
        <style>
            * { font-family: 'Inter', sans-serif; }
            h1, h2, h3, .playfair { font-family: 'Playfair Display', serif; }
            .hero-section { background: linear-gradient(135deg, #FFF8E7 0%, #FFFFFF 100%); border-radius: 48px; padding: 60px 40px; text-align: center; margin-bottom: 48px; }
            .hero-title { font-size: 56px; font-weight: 700; color: #1e293b; margin-bottom: 16px; }
            .hero-subtitle { font-size: 18px; font-weight: 300; color: #475569; max-width: 600px; margin: 0 auto 32px auto; }
            .btn-primary { background: #E0A32E !important; border: none !important; border-radius: 50px !important; padding: 12px 32px !important; font-weight: 600 !important; color: white !important; }
            .month-btn { background: #FFF3E0; border: 1px solid #E0A32E; border-radius: 60px; padding: 10px 28px; font-weight: 500; margin: 0 8px; color: #E0A32E; cursor: pointer; transition: all 0.3s ease; }
            .month-btn:hover { background: #E0A32E; color: white; }
            .month-btn-active { background: #E0A32E; color: white; border-color: #E0A32E; }
            .dish-card { height: 100%; border-radius: 24px; border: none; box-shadow: 0 4px 12px rgba(0,0,0,0.05); display: flex; flex-direction: column; transition: transform 0.3s ease, box-shadow 0.3s ease; }
            .dish-card:hover { transform: translateY(-5px); box-shadow: 0 12px 24px rgba(0,0,0,0.1); }
            .dish-card .card-body { flex: 1; display: flex; flex-direction: column; justify-content: space-between; }
            .dish-image { height: 200px; border-radius: 24px 24px 0 0; overflow: hidden; background: linear-gradient(135deg, #FFF8E7, #FFE0B2); display: flex; align-items: center; justify-content: center; }
            .dish-image img { width: 100%; height: 100%; object-fit: cover; transition: transform 0.5s ease; }
            .dish-card:hover .dish-image img { transform: scale(1.05); }
            .constructor-block { background: #F8F9FA; border-radius: 32px; padding: 48px; text-align: center; margin: 48px 0; border: 1px solid #E9ECEF; }
            .constructor-block .btn { background: #E0A32E; color: white; border: none; padding: 12px 32px; font-weight: 600; border-radius: 50px; }
            .card { border-radius: 20px !important; border: 1px solid #f0f0f0 !important; transition: 0.2s; }
            .card:hover { transform: translateY(-4px); box-shadow: 0 20px 30px -12px rgba(0,0,0,0.1) !important; }
            .badge { border-radius: 40px !important; padding: 6px 14px !important; font-weight: 500 !important; color: white !important; }
            .form-control { border-radius: 40px !important; border: 1px solid #e0e0e0 !important; padding: 12px 20px !important; }
            .form-control:focus { border-color: #E0A32E !important; box-shadow: 0 0 0 3px rgba(224,163,46,0.2) !important; }
            .search-group { display: flex; gap: 8px; margin-bottom: 16px; }
            .search-group .form-control { flex: 3; }
            .search-group .btn { flex: 1; white-space: nowrap; }
            .btn-fav { background: white !important; border: 1px solid #dee2e6 !important; border-radius: 40px !important; color: #1e293b !important; padding: 8px 20px !important; }
            .btn-fav:hover { background: #f8f9fa !important; }
            .upload-area { border: 2px dashed #E0A32E; border-radius: 24px; background: #FFF8E7; text-align: center; padding: 48px 24px; cursor: pointer; transition: all 0.3s ease; }
            .upload-area:hover { background: #FFF3E0; border-color: #c88a1a; }
            .nav-link-custom { color: #1e293b !important; text-decoration: underline !important; text-decoration-thickness: 2px !important; text-underline-offset: 6px !important; font-weight: 500 !important; background: none !important; border: none !important; padding: 0 !important; }
            .seasonal-text { font-style: italic; font-weight: 300; color: #475569; max-width: 700px; margin: 0 auto 32px auto; }
            .btn-light-outline { background: white; border: 1px solid #dee2e6; border-radius: 40px; padding: 6px 16px; font-size: 12px; color: #495057; transition: all 0.2s ease; }
            .btn-light-outline:hover { background: #f8f9fa; border-color: #E0A32E; }
            .price-text { color: #495057 !important; font-weight: 600; }
            .footer-text { color: #adb5bd; font-size: 12px; text-align: center; margin-top: 48px; padding-top: 24px; border-top: 1px solid #e9ecef; }
        </style>
    </head>
    <body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body>
</html>
'''


def create_price_chart(product):
    months = product['months']
    prices = product['price_timeline']
    current_month = datetime.now().month
    point_colors = ['#E0A32E' for _ in range(12)]
    point_colors[current_month - 1] = '#E0A32E'
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=months, y=prices, mode='lines+markers',
                             line=dict(color='#E0A32E', width=2), marker=dict(size=6, color=point_colors),
                             fill='tozeroy', fillcolor='rgba(224,163,46,0.08)'))
    fig.update_layout(height=80, margin=dict(l=5, r=5, t=10, b=5),
                      plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                      xaxis=dict(showgrid=False, tickfont=dict(size=9), tickangle=0),
                      yaxis=dict(showgrid=False, showticklabels=False))
    return fig


def create_product_card(product, is_fav=False):
    fav_icon = "❤️" if is_fav else "🤍"
    badges = []
    if product.get('premium', False):
        badges.append(dbc.Badge("Премиум", style={"fontSize": "10px", "backgroundColor": "#E0A32E", "color": "white"}))
    if product.get('rare', False):
        badges.append(dbc.Badge("Редкий", style={"fontSize": "10px", "backgroundColor": "#f44336"}))

    return dbc.Col([
        dbc.Card([
            dbc.CardBody([
                html.Div([
                    dbc.Row([
                        dbc.Col([
                            dbc.Badge(product['status'], style={"backgroundColor": product['status_color'],
                                                                "color": product['status_text_color']},
                                      className="mb-1"),
                            html.H6(product['product_original'], className="mb-1 fw-bold",
                                    style={"fontSize": "0.85rem", "height": "40px", "overflow": "hidden"}),
                            html.Small(f"{product['category']} | {product['farmer'][:20]}", className="text-muted"),
                        ], width=8),
                        dbc.Col([
                            html.Div(badges, className="text-end mb-1", style={"minHeight": "24px"}),
                            html.Strong(f"{product['current_price']} ₽", className="price-text",
                                        style={"fontSize": "16px"}),
                            html.Small("/кг", className="text-muted"),
                        ], width=4, className="text-end"),
                    ]),
                ], style={"minHeight": "80px"}),
                html.Div([
                    dcc.Graph(figure=create_price_chart(product), config={'displayModeBar': False},
                              style={"height": "80px"})
                ], style={"height": "80px", "margin": "8px 0"}),
                html.Hr(className="my-1"),
                html.Div([
                    dbc.Row([
                        dbc.Col(
                            html.Button(
                                fav_icon,
                                id={"type": "fav", "index": product["product"]},
                                style={
                                    "background": "white",
                                    "border": f"1px solid {'#ef4444' if is_fav else '#dee2e6'}",
                                    "borderRadius": "50%",
                                    "width": "36px",
                                    "height": "36px",
                                    "display": "flex",
                                    "alignItems": "center",
                                    "justifyContent": "center",
                                    "cursor": "pointer",
                                    "color": "#ef4444" if is_fav else "#adb5bd",
                                    "fontSize": "18px",
                                    "transition": "all 0.2s ease"
                                }
                            ), width="auto"
                        ),
                        dbc.Col([
                            dbc.Button("Фермер", href=product["farmer_url"], target="_blank", size="sm",
                                       className="btn-light-outline me-1"),
                            dbc.Button("Детали", href=product["url"], target="_blank", size="sm",
                                       className="btn-light-outline"),
                        ], width="auto", className="text-end"),
                    ], className="align-items-center justify-content-between")
                ], style={"marginTop": "auto"})
            ], className="p-2", style={"display": "flex", "flexDirection": "column", "height": "100%"})
        ], className="h-100 shadow-sm", style={"height": "100%"})
    ], width=12, md=6, lg=4, xl=3, className="mb-3", style={"display": "flex"})


def get_smart_recommendation(dish_name, cuisine="русская"):
    DISH_INGREDIENTS = {
        "борщ": {"ingredients": ["свекла", "капуста", "морковь", "картофель", "лук", "томаты"],
                 "advice": "Добавьте свёклу, запеченную заранее"},
        "окрошка": {"ingredients": ["огурцы", "редис", "зелень", "яйца", "квас", "картофель"],
                    "advice": "Вместо кваса можно кефир"},
        "щи": {"ingredients": ["капуста", "картофель", "морковь", "лук", "томаты"],
               "advice": "Зимой используйте квашеную капусту"},
        "уха": {"ingredients": ["рыба", "картофель", "лук", "морковь"], "advice": "Для навара — мелкая рыба"},
        "корюшка": {"ingredients": ["корюшка", "мука", "лимон"], "advice": "Жарьте на сильном огне"},
        "черемша": {"ingredients": ["черемша", "яйцо", "сметана"], "advice": "Отличный весенний салат"},
    }
    if not dish_name or len(dish_name.strip()) < 3:
        return None
    dish_lower = dish_name.lower().strip()
    for known, data in DISH_INGREDIENTS.items():
        if known in dish_lower or dish_lower in known:
            return {"found": True, "dish_name": known, "ingredients": data["ingredients"], "advice": data["advice"]}
    return {"found": False, "dish_name": dish_name, "advice": "Попробуйте добавить сезонные овощи"}


def create_recommendation_card(rec):
    if rec.get('found'):
        return dbc.Alert([
            html.H6(f"🍲 {rec['dish_name'].capitalize()}", className="mb-2"),
            html.P(f"Ингредиенты: {', '.join(rec['ingredients'])}", className="small"),
            html.P(f"💡 {rec['advice']}", className="small text-success"),
        ], color="light")
    return dbc.Alert([
        html.H6(f"🍲 {rec['dish_name']}", className="mb-2"),
        html.P(rec['advice'], className="small"),
    ], color="warning")


def extract_ingredients_from_pdf(contents):
    try:
        content_type, content_string = contents.split(',')
        decoded = base64.b64decode(content_string)
        pdf_file = io.BytesIO(decoded)
        text = ""
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
        words = re.findall(r'[а-яa-z]+', text.lower())
        all_ingredients = set(products_db['product'].tolist())
        found_ingredients = set()
        for word in words:
            if len(word) > 3:
                for ingredient in all_ingredients:
                    if ingredient in word or word in ingredient:
                        found_ingredients.add(ingredient)
        return list(found_ingredients)
    except:
        return []


def analyze_pdf_menu(ingredients):
    if not ingredients:
        return None
    results = {"ingredients_found": ingredients, "products": []}
    for ing in ingredients[:20]:
        products = products_db[products_db['product'].str.contains(ing, case=False, na=False, regex=False)]
        for _, p in products.head(3).iterrows():
            results["products"].append({
                "name": p['product_original'], "status": p['status'],
                "farmer": p['farmer'], "price": p['current_price'], "farmer_url": p['farmer_url']
            })
    return results


def create_pdf_analysis_card(analysis):
    if not analysis or not analysis.get("ingredients_found"):
        return dbc.Alert("Не удалось распознать PDF", color="warning")

    products_html = []
    for p in analysis["products"][:8]:
        status_style = {"color": "#E0A32E", "fontWeight": "500"} if p['status'] == "В сезоне" else {}
        products_html.append(
            dbc.ListGroupItem([
                html.Div([
                    html.Strong(p['name'], style={"fontSize": "14px"}),
                    html.Span(f" • {p['status']}", style=status_style),
                ], className="d-flex justify-content-between align-items-center"),
                html.Small(f"{p['farmer']} • {p['price']} ₽/кг", className="text-muted d-block mt-1",
                           style={"fontSize": "11px"}),
                html.Div([
                    dbc.Button("🌾 Фермер", href=p['farmer_url'], target="_blank", size="sm", className="mt-2 w-100",
                               style={
                                   "backgroundColor": "#E0A32E",
                                   "border": "none",
                                   "borderRadius": "50px",
                                   "fontSize": "11px",
                                   "fontWeight": "500",
                                   "padding": "6px 16px",
                                   "cursor": "pointer"
                               })
                ], className="w-100")
            ], className="mb-2", style={"borderRadius": "12px", "border": "1px solid #f0f0f0", "padding": "10px"})
        )

    return dbc.Card([
        dbc.CardBody([
            html.H5([html.I(className="fas fa-check-circle", style={"color": "#E0A32E", "marginRight": "8px"}),
                     f"Найдено ингредиентов: {len(analysis['ingredients_found'])}"],
                    className="mb-3", style={"fontWeight": "600", "color": "#1e293b"}),
            html.P("Подходящие продукты от фермеров:", className="fw-bold mb-2", style={"fontSize": "13px"}),
            html.Div(products_html if products_html else [html.P("Нет совпадений", className="text-muted small")])
        ])
    ], className="border-0 shadow-sm", style={"borderRadius": "20px"})


seasonal_dishes_data = {
    "март": [
        {"name": "Зелёные щи с крапивой", "desc": "Крапива, щавель, яйцо, сметана",
         "image": "/assets/dishes/march_1.jpg"},
        {"name": "Блины с икрой", "desc": "Тонкие блины, красная икра, сметана", "image": "/assets/dishes/march_2.jpg"},
        {"name": "Берёзовый сок", "desc": "Натуральный напиток с мятой и лимоном",
         "image": "/assets/dishes/march_3.jpg"}
    ],
    "апрель": [
        {"name": "Окрошка весенняя", "desc": "Редис, огурцы, зелень, квас", "image": "/assets/dishes/april_1.jpg"},
        {"name": "Свекольник", "desc": "Свёкла, огурцы, кефир, укроп", "image": "/assets/dishes/april_2.png"},
        {"name": "Кулич пасхальный", "desc": "Творог, изюм, цедра, глазурь", "image": "/assets/dishes/april_3.jpg"}
    ],
    "май": [
        {"name": "Жареная корюшка", "desc": "Корюшка, мука, лимон, зелень", "image": "/assets/dishes/may_1.jpg"},
        {"name": "Салат с черемшой", "desc": "Черемша, яйцо, сметана, редис", "image": "/assets/dishes/may_2.jpg"},
        {"name": "Пряженые пирожки", "desc": "Зелень, яйцо, зелёный лук", "image": "/assets/dishes/may_3.jpg"}
    ],
}


def create_dish_card(dish, idx, month_key):
    return dbc.Col([
        dbc.Card([
            html.Div(
                html.Img(src=dish["image"], style={"width": "100%", "height": "200px", "objectFit": "cover"}),
                className="dish-image",
                style={"height": "200px", "overflow": "hidden"}
            ),
            dbc.CardBody([
                html.H5(dish["name"], className="fw-bold mb-2", style={"fontSize": "18px"}),
                html.P(dish["desc"], className="text-muted small mb-3"),
                dbc.Button("Заказать ингредиенты",
                           id={"type": "order-dish", "index": dish["name"]},
                           color="primary", size="sm", className="w-100 mt-auto")
            ], className="d-flex flex-column justify-content-between")
        ], className="dish-card h-100")
    ], width=12, md=4, className="mb-4")


def landing_page():
    return html.Div([
        dbc.Row([
            dbc.Col([
                html.Div([
                    html.H1("Закупайте напрямую", className="hero-title"),
                    html.H1("у производителей", className="hero-title", style={"color": "#1e293b"}),
                    html.P("Все продукты, которые нужны для ресторана от местных фермеров", className="hero-subtitle"),
                    dbc.Button("Перейти в каталог", id="to-catalog-btn", color="primary", size="lg")
                ], className="hero-section")
            ], width=12)
        ]),
        dbc.Row([
            dbc.Col([
                html.H3("Сезонный эксклюзив", className="text-center playfair mb-2",
                        style={"fontSize": "42px", "fontWeight": "700"}),
                html.P("от фермеров с доставкой", className="text-center text-muted mb-3",
                       style={"fontSize": "18px", "fontWeight": "300"}),
                html.P(
                    "Каждый месяц мы подбираем трендовые ингредиенты и готовим для вас 3 идеи блюд от топ-шефов. Используйте их в своём меню.",
                    className="text-center seasonal-text mb-4"),
                html.Div([
                    html.Button("Март", id="month-mar-landing", className="month-btn", n_clicks=0),
                    html.Button("Апрель", id="month-apr-landing", className="month-btn month-btn-active", n_clicks=0),
                    html.Button("Май", id="month-may-landing", className="month-btn", n_clicks=0),
                ], className="text-center mb-5"),
                html.Div(id="seasonal-dishes-landing", className="mb-4"),
            ], width=12)
        ], className="mb-5"),
        dbc.Row([
            dbc.Col([
                html.Div([
                    html.I(className="fas fa-chart-line",
                           style={"fontSize": "48px", "marginBottom": "20px", "color": "#E0A32E"}),
                    html.H3("Онлайн конструктор меню", style={"fontWeight": "700", "marginBottom": "16px"}),
                    html.P(
                        "Проанализируйте своё меню за секунды. Мы подберём сезонные продукты и фермеров, заменим несезонные ингредиенты и дадим готовые идеи блюд.",
                        style={"maxWidth": "700px", "margin": "0 auto 24px auto", "color": "#495057"}),
                    dbc.Button("Попробовать", id="to-constructor-btn")
                ], className="constructor-block")
            ], width=12)
        ])
    ])


def catalog_page():
    return html.Div([
        html.Div(className="mb-3", children=[
            dbc.Button("На главную", href="/", className="nav-link-custom")
        ]),
        dbc.Row([
            dbc.Col([
                html.Div([
                    dbc.Input(id="search-input", type="text", placeholder="Поиск продуктов...",
                              className="form-control"),
                    dbc.Button("Найти", id="search-btn", color="primary"),
                    dbc.Button("Избранное", id="fav-btn", className="btn-fav"),
                ], className="search-group"),
                html.Div(id="search-status", className="mb-2 small text-muted"),
            ], width=12)
        ]),
        dbc.Row([
            dbc.Col([
                html.Div([html.Span("Фильтры:", className="me-3 fw-bold"),
                          dbc.Badge("Сбросить всё", id="reset-filters", color="secondary",
                                    style={"cursor": "pointer"})], className="mb-2"),
                dbc.Row([
                    dbc.Col(dcc.Dropdown(id="season-dropdown", options=[
                        {"label": "Все сезоны", "value": "all"}, {"label": "В сезоне", "value": "in_season"},
                        {"label": "Скоро", "value": "soon"}, {"label": "Не сезон", "value": "out_season"},
                    ], value="all"), width=3),
                    dbc.Col(dcc.Dropdown(id="category-dropdown",
                                         options=[{"label": "Все категории", "value": "all"}] + [
                                             {"label": c, "value": c} for c in categories_list], value="all"), width=3),
                    dbc.Col(dcc.Dropdown(id="status-dropdown", options=[
                        {"label": "Все типы", "value": "all"}, {"label": "Премиум", "value": "premium"},
                        {"label": "Редкие", "value": "rare"},
                    ], value="all"), width=3),
                    dbc.Col(dcc.Dropdown(id="sort-dropdown", options=[
                        {"label": "По умолчанию", "value": "default"}, {"label": "По сезону", "value": "season"},
                        {"label": "По категории", "value": "category"},
                        {"label": "По цене (возр.)", "value": "price_asc"},
                        {"label": "По цене (убыв.)", "value": "price_desc"},
                    ], value="default"), width=3),
                ])
            ], width=12)
        ], className="mb-3 p-3 rounded-3",
            style={"background": "#fff", "border": "1px solid #e0e0e0", "borderRadius": "24px"}),
        html.H4("Продукты", className="mb-3"),
        dbc.Row([dbc.Col(id="results-container", width=12)])
    ])


def recommend_page(dish_value=""):
    return html.Div([
        html.Div(className="mb-3", children=[
            dbc.Button("На главную", href="/", className="nav-link-custom")
        ]),
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Умный анализатор блюд",
                                   style={"backgroundColor": "#E0A32E", "borderRadius": "20px 20px 0 0",
                                          "color": "white"}),
                    dbc.CardBody([
                        html.P("Введите название блюда, и я проанализирую ингредиенты:"),
                        dcc.Dropdown(id="cuisine-select", options=[
                            {"label": "Русская", "value": "русская"}, {"label": "Европейская", "value": "европейская"},
                            {"label": "Итальянская", "value": "итальянская"},
                            {"label": "Французская", "value": "française"},
                        ], value="русская", className="mb-3"),
                        dbc.Input(id="dish-input", type="text", placeholder="Название блюда...", value=dish_value,
                                  className="mb-2"),
                        dbc.Button("Анализировать", id="rec-btn", color="primary", className="w-100 mb-3"),
                        html.Div(id="rec-output"),
                    ])
                ])
            ], width=12)
        ])
    ])


def pdf_page():
    return html.Div([
        html.Div(className="mb-3", children=[
            dbc.Button("На главную", href="/", className="nav-link-custom")
        ]),
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Загрузка меню ресторана",
                                   style={"backgroundColor": "#E0A32E", "borderRadius": "20px 20px 0 0",
                                          "color": "white"}),
                    dbc.CardBody([
                        html.P(
                            "Загрузите PDF-файл с вашим меню. Система проанализирует ингредиенты и подберет сезонные продукты.",
                            className="mb-3"),
                        dcc.Upload(id="upload-pdf-menu", children=html.Div([
                            html.I(className="fas fa-cloud-upload-alt", style={"fontSize": "40px", "color": "#E0A32E"}),
                            html.P("Перетащите файл сюда или нажмите", style={"marginTop": "10px"}),
                        ], className="upload-area"), multiple=False),
                        html.Div(id="pdf-upload-status", className="mt-3"),
                        html.Div(id="pdf-analysis-output", className="mt-4"),
                    ])
                ])
            ], width=12)
        ])
    ])


def footer():
    return html.Div([
        html.Hr(),
        html.P("2026 Своё Шеф | Платформа Россельхозбанка", className="footer-text")
    ])


app.layout = dbc.Container([
    dcc.Location(id="url", refresh=False),
    dcc.Store(id="favorites-store", data=favorites),
    dcc.Store(id="selected-dish-name", data=""),
    html.Div(id="page-content"),
    footer()
], fluid=True, className="px-4 py-3")


@app.callback(
    Output("page-content", "children"),
    Input("url", "pathname"),
    State("selected-dish-name", "data")
)
def router(pathname, stored_dish):
    if pathname == "/catalog":
        return catalog_page()
    elif pathname == "/pdf":
        return pdf_page()
    elif pathname == "/recommend":
        return recommend_page(stored_dish)
    return landing_page()


@app.callback(
    Output("url", "pathname", allow_duplicate=True),
    Output("selected-dish-name", "data"),
    Input({"type": "order-dish", "index": dash.ALL}, "n_clicks"),
    prevent_initial_call=True
)
def open_recommend(clicks):
    ctx = callback_context
    if not ctx.triggered or not clicks or max([c or 0 for c in clicks]) == 0:
        raise dash.exceptions.PreventUpdate
    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
    if "order-dish" not in trigger_id:
        raise dash.exceptions.PreventUpdate
    import ast
    btn_info = ast.literal_eval(trigger_id)
    dish_name = btn_info["index"]
    return "/recommend", dish_name


@app.callback(
    Output("seasonal-dishes-landing", "children"),
    Input("month-mar-landing", "n_clicks"),
    Input("month-apr-landing", "n_clicks"),
    Input("month-may-landing", "n_clicks")
)
def update_dishes(mar, apr, may):
    ctx = callback_context
    if not ctx.triggered:
        month_key = "апрель"
    else:
        btn_id = ctx.triggered[0]['prop_id'].split('.')[0]
        if btn_id == "month-mar-landing":
            month_key = "март"
        elif btn_id == "month-may-landing":
            month_key = "май"
        else:
            month_key = "апрель"
    dishes = seasonal_dishes_data[month_key]
    return dbc.Row([create_dish_card(d, idx, month_key) for idx, d in enumerate(dishes)], className="g-4")


@app.callback(
    [Output("month-mar-landing", "className"), Output("month-apr-landing", "className"),
     Output("month-may-landing", "className")],
    Input("month-mar-landing", "n_clicks"), Input("month-apr-landing", "n_clicks"),
    Input("month-may-landing", "n_clicks")
)
def active_month_btn(mar, apr, may):
    ctx = callback_context
    if not ctx.triggered:
        return "month-btn", "month-btn month-btn-active", "month-btn"
    btn_id = ctx.triggered[0]['prop_id'].split('.')[0]
    if btn_id == "month-mar-landing":
        return "month-btn month-btn-active", "month-btn", "month-btn"
    elif btn_id == "month-may-landing":
        return "month-btn", "month-btn", "month-btn month-btn-active"
    else:
        return "month-btn", "month-btn month-btn-active", "month-btn"


@app.callback(
    Output("url", "pathname"),
    Input("to-catalog-btn", "n_clicks"),
    Input("to-constructor-btn", "n_clicks"),
    prevent_initial_call=True
)
def navigate(to_cat, to_const):
    ctx = callback_context
    if not ctx.triggered:
        return "/"
    btn_id = ctx.triggered[0]['prop_id'].split('.')[0]
    if btn_id == "to-catalog-btn":
        return "/catalog"
    elif btn_id == "to-constructor-btn":
        return "/pdf"
    return "/"


@app.callback(
    [Output("results-container", "children"), Output("search-status", "children")],
    Input("search-btn", "n_clicks"), Input("season-dropdown", "value"), Input("category-dropdown", "value"),
    Input("status-dropdown", "value"), Input("sort-dropdown", "value"), Input("fav-btn", "n_clicks"),
    Input("reset-filters", "n_clicks"), Input("favorites-store", "data"),
    State("search-input", "value")
)
def update_catalog(btn, season, cat, status, sort_by, fav_btn, reset, fav_list, search_val):
    ctx = callback_context
    trigger = ctx.triggered[0]["prop_id"] if ctx.triggered else ""
    fav_list = fav_list or []
    if "reset" in trigger:
        search_val = ""
        season = "all"
        cat = "all"
        status = "all"
        sort_by = "default"
    filtered = products_db.copy()
    if "search-btn" in trigger and search_val and len(search_val) >= 2:
        ids = fuzzy_search(search_val, products_list)
        filtered = filtered[filtered["id"].isin(ids)] if ids else filtered.head(0)
        status_text = f"Найдено {len(filtered)} продуктов" if not filtered.empty else f"Ничего не найдено"
    elif "fav-btn" in trigger:
        filtered = filtered[filtered["product"].isin(fav_list)]
        status_text = f"Избранное: {len(filtered)} продуктов"
    else:
        filtered = filtered.head(24)
        status_text = f"Показано {len(filtered)} из {len(products_db)} продуктов"
        if season == "in_season":
            filtered = filtered[filtered["status"] == "В сезоне"]
        elif season == "soon":
            filtered = filtered[filtered["status"] == "Скоро"]
        elif season == "out_season":
            filtered = filtered[filtered["status"] == "Не сезон"]
        if cat != "all":
            filtered = filtered[filtered["category"] == cat]
        if status == "premium":
            filtered = filtered[filtered["premium"] == True]
        elif status == "rare":
            filtered = filtered[filtered["rare"] == True]
        if sort_by == "season":
            order = {"В сезоне": 0, "Скоро": 1, "Не сезон": 2}
            filtered["_sort"] = filtered["status"].map(order)
            filtered = filtered.sort_values("_sort")
        elif sort_by == "category":
            filtered = filtered.sort_values("category")
        elif sort_by == "price_asc":
            filtered = filtered.sort_values("current_price")
        elif sort_by == "price_desc":
            filtered = filtered.sort_values("current_price", ascending=False)
    if filtered.empty:
        return html.Div(dbc.Alert("Ничего не найдено", color="info")), status_text
    fav_set = set(fav_list)
    cards = dbc.Row(
        [create_product_card(row.to_dict(), row["product"] in fav_set) for _, row in filtered.head(48).iterrows()],
        className="g-3")
    return cards, status_text


@app.callback(
    Output("favorites-store", "data", allow_duplicate=True),
    Input({"type": "fav", "index": dash.ALL}, "n_clicks"),
    State("favorites-store", "data"),
    prevent_initial_call=True
)
def toggle_fav(clicks, fav_list):
    if not clicks or not any(clicks):
        return fav_list
    ctx = callback_context
    if not ctx.triggered:
        return fav_list
    import ast
    trigger = ctx.triggered[0]['prop_id'].split('.')[0]
    product = ast.literal_eval(trigger)["index"]
    if fav_list is None:
        fav_list = []
    if product in fav_list:
        fav_list.remove(product)
    else:
        fav_list.append(product)
    with open(FAVORITES_FILE, 'w') as f:
        json.dump(fav_list, f)
    return fav_list


@app.callback(
    [Output("season-dropdown", "value"), Output("category-dropdown", "value"), Output("status-dropdown", "value"),
     Output("sort-dropdown", "value")],
    Input("reset-filters", "n_clicks"), prevent_initial_call=True
)
def reset_filters(n):
    return "all", "all", "all", "default"


@app.callback(
    Output("rec-output", "children"),
    Input("rec-btn", "n_clicks"),
    State("dish-input", "value"),
    State("cuisine-select", "value"),
    prevent_initial_call=True
)
def recommend(n, dish, cuisine):
    if not dish:
        return dbc.Alert("Введите блюдо", color="warning")
    rec = get_smart_recommendation(dish, cuisine)
    return create_recommendation_card(rec)


@app.callback(
    [Output("pdf-upload-status", "children"), Output("pdf-analysis-output", "children")],
    Input("upload-pdf-menu", "contents"),
    prevent_initial_call=True
)
def handle_pdf(contents):
    if contents:
        ings = extract_ingredients_from_pdf(contents)
        if ings:
            analysis = analyze_pdf_menu(ings)
            return dbc.Alert(f"✓ Найдено {len(ings)} ингредиентов", color="success",
                             className="small"), create_pdf_analysis_card(analysis)
        return dbc.Alert("Не удалось распознать PDF", color="warning", className="small"), None
    return "", None


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("СВОЁ ШЕФ - ДАШБОРД УСПЕШНО ЗАПУЩЕН")
    print("=" * 60)
    print("ОТКРОЙТЕ В БРАУЗЕРЕ: http://127.0.0.1:8050")
    print("=" * 60)
    print("🛑 Остановить сервер: Ctrl+C")
    print("=" * 60 + "\n")
    app.run(debug=False, port=8050)
