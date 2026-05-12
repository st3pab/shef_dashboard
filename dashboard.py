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

df_raw = pd.read_csv("data/farmers_sku.csv")


try:
    df_seasonal_products = pd.read_csv("data/seasonal_products.csv", encoding='utf-8-sig')
except:
    df_seasonal_products = pd.DataFrame()

try:
    df_seasonal_dishes = pd.read_csv("data/seasonal_dishes.csv", encoding='utf-8-sig')
except:
    df_seasonal_dishes = pd.DataFrame()

SEASON_CACHE = {}
CATEGORY_CACHE = {}
PRICE_TIMELINE_CACHE = {}

# Категории из файла
CATEGORIES_FROM_FILE = set()


def get_season_fast(product_name):
    if product_name in SEASON_CACHE:
        return SEASON_CACHE[product_name]

    name_lower = product_name.lower()
    rules = [
        (['клубник', 'земляник'], (5, 8, "Ягодный сезон")),
        (['малин'], (6, 8, "Ягодный сезон")),
        (['смородин'], (7, 8, "Ягодный сезон")),
        (['яблок'], (8, 10, "Фруктовый сезон")),
        (['груш'], (8, 9, "Фруктовый сезон")),
        (['тыкв'], (9, 11, "Осенний урожай")),
        (['кабачк'], (6, 8, "Летний сезон")),
        (['огурц'], (6, 8, "Летний сезон")),
        (['помидор', 'томат'], (7, 9, "Летний сезон")),
        (['баклажан'], (7, 9, "Летний сезон")),
        (['перец'], (7, 9, "Летний сезон")),
        (['базилик'], (6, 8, "Зелень")),
        (['укроп', 'петрушк'], (5, 9, "Зелень")),
        (['салат'], (5, 9, "Зелень")),
        (['щавел'], (4, 6, "Весенний сезон")),
        (['редис'], (5, 6, "Весенний сезон")),
        (['чай', 'сбор', 'уксус'], (1, 12, "Круглый год")),
    ]

    for keywords, season in rules:
        if any(kw in name_lower for kw in keywords):
            SEASON_CACHE[product_name] = season
            return season

    SEASON_CACHE[product_name] = (1, 12, "Круглый год")
    return (1, 12, "Круглый год")


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

    season_start, season_end, _ = get_season_fast(product_name)
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

    result = (months, prices)
    PRICE_TIMELINE_CACHE[cache_key] = result
    return result


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


# База знаний для блюд
DISH_INGREDIENTS = {
    "борщ": {
        "ingredients": ["свекла", "капуста", "морковь", "картофель", "лук", "томаты"],
        "seasonal_replacements": {
            "томаты": ["квашеная капуста", "соленые помидоры"],
            "капуста": ["квашеная капуста", "молодая капуста"]
        },
        "advice": "Для насыщенного вкуса добавьте свёклу, запеченную заранее"
    },
    "окрошка": {
        "ingredients": ["огурцы", "редис", "зелень", "яйца", "квас", "картофель"],
        "seasonal_replacements": {
            "огурцы": ["редис", "зеленый лук"],
            "редис": ["редька", "дайкон"]
        },
        "advice": "Вместо кваса можно использовать кефир или тань"
    },
    "щи": {
        "ingredients": ["капуста", "картофель", "морковь", "лук", "томаты"],
        "seasonal_replacements": {
            "капуста": ["квашеная капуста", "щавель", "крапива"],
            "томаты": ["щавель", "соленые помидоры"]
        },
        "advice": "Зеленые щи готовят из щавеля и крапивы весной"
    },
    "уха": {
        "ingredients": ["рыба", "картофель", "лук", "морковь"],
        "seasonal_replacements": {
            "рыба": ["налим", "судак", "щука", "лосось"]
        },
        "advice": "Для навара используйте мелкую рыбу"
    },
    "пельмени": {
        "ingredients": ["мука", "фарш", "лук", "бульон"],
        "seasonal_replacements": {},
        "advice": "Для соуса подавайте сметану и свежую зелень"
    },
    "блины": {
        "ingredients": ["мука", "молоко", "яйца", "масло"],
        "seasonal_replacements": {},
        "advice": "Сезонные начинки: весной - творог и зелень, летом - ягоды"
    },
}


def get_smart_recommendation(dish_name, cuisine="русская"):
    if not dish_name or len(dish_name.strip()) < 3:
        return None

    dish_lower = dish_name.lower().strip()
    current_season = get_current_season()

    base_dish = None
    for known_dish in DISH_INGREDIENTS:
        if known_dish in dish_lower or dish_lower in known_dish:
            base_dish = known_dish
            break

    if base_dish:
        dish_data = DISH_INGREDIENTS[base_dish]
        ingredients = dish_data["ingredients"]
        replacements = dish_data.get("seasonal_replacements", {})

        available_ingredients = []
        missing_ingredients = []
        replacement_suggestions = []

        for ing in ingredients:
            farmers_with_ing = products_db[products_db['product_original'].str.contains(ing, case=False, na=False)]
            in_season = farmers_with_ing[farmers_with_ing['status'] == "В сезоне"]

            if not in_season.empty:
                available_ingredients.append({
                    "name": ing,
                    "in_season": True,
                    "farmers": in_season.head(2)[['farmer', 'farmer_url', 'region', 'current_price']].to_dict('records')
                })
            else:
                if ing in replacements:
                    replacement_found = False
                    for rep in replacements[ing]:
                        farmers_with_rep = products_db[
                            products_db['product_original'].str.contains(rep, case=False, na=False)]
                        rep_in_season = farmers_with_rep[farmers_with_rep['status'] == "В сезоне"]
                        if not rep_in_season.empty:
                            replacement_suggestions.append({
                                "original": ing,
                                "replacement": rep,
                                "farmers": rep_in_season.head(2)[
                                    ['farmer', 'farmer_url', 'region', 'current_price']].to_dict('records')
                            })
                            replacement_found = True
                            break
                    if not replacement_found:
                        missing_ingredients.append(ing)
                else:
                    missing_ingredients.append(ing)

        seasonal_products_list = []
        if not df_seasonal_products.empty:
            seasonal_data = df_seasonal_products[df_seasonal_products['season'] == current_season].head(5)
            seasonal_products_list = seasonal_data.to_dict('records')

        return {
            "found": True,
            "dish_name": base_dish,
            "cuisine": cuisine,
            "ingredients": ingredients,
            "available": available_ingredients,
            "missing": missing_ingredients,
            "replacements": replacement_suggestions,
            "seasonal_products": seasonal_products_list,
            "advice": dish_data["advice"],
            "current_season": current_season
        }
    else:
        matching_products = products_db[products_db['product_original'].str.contains(dish_lower, case=False, na=False)]
        if not matching_products.empty:
            return {
                "found": "product_match",
                "dish_name": dish_name,
                "cuisine": cuisine,
                "matching_products": matching_products.head(5).to_dict('records'),
                "current_season": current_season
            }

        if not df_seasonal_products.empty:
            seasonal_data = df_seasonal_products[df_seasonal_products['season'] == current_season].head(5).to_dict(
                'records')
        else:
            seasonal_data = []

        return {
            "found": False,
            "dish_name": dish_name,
            "cuisine": cuisine,
            "current_season": current_season,
            "seasonal_products": seasonal_data
        }


def extract_ingredients_from_pdf(contents):
    """Извлечение ингредиентов из PDF меню"""
    try:
        content_type, content_string = contents.split(',')
        decoded = base64.b64decode(content_string)
        pdf_file = io.BytesIO(decoded)

        text = ""
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""

        # Ищем ингредиенты в тексте PDF
        words = re.findall(r'[а-яa-z]+', text.lower())
        all_ingredients = set(products_db['product'].tolist())

        found_ingredients = set()
        for word in words:
            if len(word) > 3:
                for ingredient in all_ingredients:
                    if ingredient in word or word in ingredient:
                        found_ingredients.add(ingredient)

        return list(found_ingredients)
    except Exception as e:
        print(f"Ошибка при обработке PDF: {e}")
        return []


def analyze_pdf_menu(ingredients):
    """Анализ найденных ингредиентов из PDF"""
    if not ingredients:
        return None

    results = {
        "ingredients_found": ingredients,
        "products": [],
        "recommendations": []
    }

    for ing in ingredients[:20]:
        products = products_db[products_db['product'].str.contains(ing, case=False, na=False, regex=False)]
        if not products.empty:
            for _, p in products.head(3).iterrows():
                results["products"].append({
                    "name": p['product_original'],
                    "status": p['status'],
                    "farmer": p['farmer'],
                    "region": p['region'],
                    "price": p['current_price'],
                    "farmer_url": p['farmer_url']
                })

    # Рекомендации по сезонным заменам
    current_season = get_current_season()
    if not df_seasonal_products.empty:
        seasonal = df_seasonal_products[df_seasonal_products['season'] == current_season].head(5)
        for _, s in seasonal.iterrows():
            results["recommendations"].append({
                "name": s.get('product_name', ''),
                "description": s.get('description', '')
            })

    return results


# ========== ОБРАБОТКА ДАННЫХ ==========
products_list = []
all_categories = set()

for idx, row in df_raw.iterrows():
    product_name = row.get('name_product', f"Продукт_{idx}")
    if pd.isna(product_name):
        continue

    # Берём категорию из файла
    category = row.get('category', 'Другое')
    if pd.isna(category) or category == '':
        category = 'Другое'
    all_categories.add(category)

    season_start, season_end, _ = get_season_fast(product_name)
    premium = is_premium_fast(product_name, row.get('product_description', ''))
    rare = is_rare_fast(product_name, row.get('product_description', ''))
    region = str(row.get('region', 'Россия'))[:20]

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
        status_color = "#2e7d32"
    elif current_month < season_start:
        status = "Скоро"
        status_color = "#ed6c02"
    else:
        status = "Не сезон"
        status_color = "#94a3b8"

    product_data = {
        "id": idx,
        "product": str(product_name).lower(),
        "product_original": str(product_name)[:60],
        "category": category,
        "season_start": season_start,
        "season_end": season_end,
        "status": status,
        "status_color": status_color,
        "farmer": str(row.get('shop_name', 'Фермер'))[:35],
        "region": region,
        "premium": premium,
        "rare": rare,
        "current_price": price_timeline[current_month - 1],
        "price_timeline": price_timeline,
        "months": months,
        "url": str(row.get('url_product', '#')),
        "farmer_url": str(row.get('url_farmer', '#'))
    }

    products_list.append(product_data)

products_db = pd.DataFrame(products_list)
categories_list = sorted([c for c in all_categories if c and c != 'nan'])

FAVORITES_FILE = "favorites.json"
if os.path.exists(FAVORITES_FILE):
    with open(FAVORITES_FILE, 'r') as f:
        favorites = json.load(f)
else:
    favorites = []

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
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
            * { font-family: 'Inter', sans-serif; }
            .card { transition: all 0.3s ease; cursor: pointer; border-radius: 16px !important; border: 1px solid #f0f0f0 !important; }
            .card:hover { transform: translateY(-4px); box-shadow: 0 12px 24px rgba(46,125,50,0.12) !important; }
            .btn-primary { background: linear-gradient(135deg, #2E7D32 0%, #388E3C 100%) !important; border: none !important; border-radius: 12px !important; padding: 8px 20px !important; font-weight: 500 !important; color: white !important; }
            .btn-primary:hover { background: linear-gradient(135deg, #1B5E20 0%, #2E7D32 100%) !important; transform: translateY(-1px); }
            .btn-fav { background: #ef4444 !important; border: none !important; border-radius: 12px !important; color: white !important; font-weight: 500 !important; }
            .btn-fav:hover { background: #dc2626 !important; transform: translateY(-1px); }
            .btn-heart { background: white !important; border: 1px solid #e0e0e0 !important; border-radius: 50% !important; width: 36px !important; height: 36px !important; padding: 0px !important; display: flex !important; align-items: center !important; justify-content: center !important; font-size: 18px !important; }
            .btn-heart:hover { background: #fee2e2 !important; border-color: #ef4444 !important; }
            .btn-heart-fav { background: #fee2e2 !important; border: 1px solid #ef4444 !important; color: #ef4444 !important; border-radius: 50% !important; width: 36px !important; height: 36px !important; padding: 0px !important; display: flex !important; align-items: center !important; justify-content: center !important; font-size: 18px !important; }
            .nav-tabs .nav-link { color: #666 !important; font-weight: 500; border: none !important; padding: 10px 20px !important; margin-right: 5px !important; }
            .nav-tabs .nav-link.active { color: #2E7D32 !important; font-weight: 600; border-bottom: 3px solid #2E7D32 !important; background: transparent !important; }
            .form-control { border-radius: 12px !important; border: 1px solid #e0e0e0 !important; }
            .form-control:focus { border-color: #2E7D32 !important; box-shadow: 0 0 0 2px rgba(46,125,50,0.2) !important; }
            .badge { border-radius: 20px !important; font-weight: 500 !important; padding: 4px 10px !important; color: white !important; }
            .card-body { padding: 1rem !important; }
            hr { margin: 0.5rem 0 !important; }
            .tab-content { padding-top: 20px; }
            .upload-area { border: 2px dashed #2E7D32; border-radius: 16px; background: #f8fafc; text-align: center; padding: 30px; cursor: pointer; transition: all 0.3s ease; }
            .upload-area:hover { background: #e8f5e9; border-color: #1B5E20; }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''

app.layout = dbc.Container([
    dcc.Store(id="favorites-store", data=favorites),

    dbc.Row([
        dbc.Col([
            html.H1("Своё Шеф", className="display-4 mb-0", style={
                "fontWeight": "700",
                "color": "#1e293b"
            }),
            html.P("Поиск сезонных продуктов от фермеров", className="text-muted", style={"fontSize": "14px"}),
        ], width=8),
        dbc.Col([
            dbc.Badge(id="stats-badge", className="float-end mt-2", style={
                "fontSize": "13px",
                "padding": "6px 12px",
                "backgroundColor": "#2E7D32",
                "borderRadius": "20px",
                "color": "white"
            }),
        ], width=4),
    ], className="mt-3 mb-4", style={"borderBottom": "3px solid #2E7D32", "paddingBottom": "15px"}),

    dbc.Tabs([
        dbc.Tab(label="Поиск продуктов", children=[
            dbc.Row([
                dbc.Col([
                    dbc.Row([
                        dbc.Col([
                            dbc.Input(id="search-input", type="text", placeholder="Поиск продуктов...",
                                      className="form-control"),
                        ], width=8, style={"paddingRight": "8px"}),
                        dbc.Col([
                            dbc.Button("Найти", id="search-btn", color="primary", className="w-100"),
                        ], width=2, style={"paddingLeft": "0px", "paddingRight": "8px"}),
                        dbc.Col([
                            dbc.Button("Избранное", id="fav-btn", className="btn-fav w-100"),
                        ], width=2, style={"paddingLeft": "0px"}),
                    ], className="g-0 mb-3"),
                    html.Div(id="search-status", className="mb-2 small text-muted"),
                ], width=12)
            ]),

            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Span("Фильтры:", className="me-3 fw-bold"),
                        dbc.Badge("Сбросить всё", id="reset-filters", color="secondary", style={"cursor": "pointer"}),
                    ], className="mb-2"),
                    dbc.Row([
                        dbc.Col(dcc.Dropdown(id="season-dropdown", options=[
                            {"label": "Все сезоны", "value": "all"},
                            {"label": "В сезоне", "value": "in_season"},
                            {"label": "Скоро", "value": "soon"},
                            {"label": "Не сезон", "value": "out_season"},
                        ], value="all"), width=3),
                        dbc.Col(dcc.Dropdown(id="category-dropdown", options=[
                                                                                 {"label": "Все категории",
                                                                                  "value": "all"}] +
                                                                             [{"label": c, "value": c} for c in
                                                                              categories_list],
                                             value="all"), width=3),
                        dbc.Col(dcc.Dropdown(id="status-dropdown", options=[
                            {"label": "Все типы", "value": "all"},
                            {"label": "Премиум", "value": "premium"},
                            {"label": "Редкие", "value": "rare"},
                        ], value="all"), width=3),
                        dbc.Col(dcc.Dropdown(id="sort-dropdown", options=[
                            {"label": "По умолчанию", "value": "default"},
                            {"label": "По сезону", "value": "season"},
                            {"label": "По категории", "value": "category"},
                            {"label": "По цене (возр.)", "value": "price_asc"},
                            {"label": "По цене (убыв.)", "value": "price_desc"},
                        ], value="default"), width=3),
                    ])
                ], width=12)
            ], className="mb-3 p-3 rounded-3",
                style={"background": "#fff", "border": "1px solid #e0e0e0", "borderRadius": "16px",
                       "boxShadow": "0 2px 8px rgba(0,0,0,0.05)"}),

            html.H4("Продукты", className="mb-3", style={"fontWeight": "600"}),
            dbc.Row([dbc.Col(id="results-container", width=12)]),
        ]),

        dbc.Tab(label="Рекомендации для меню", children=[
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader("Умный анализатор блюд",
                                       style={"backgroundColor": "#2E7D32", "borderRadius": "12px 12px 0 0",
                                              "color": "white"}),
                        dbc.CardBody([
                            html.P("Введите название блюда, и я проанализирую ингредиенты:"),

                            html.Label("Тип кухни:", className="mt-2"),
                            dcc.Dropdown(
                                id="cuisine-select",
                                options=[
                                    {"label": "Русская", "value": "русская"},
                                    {"label": "Европейская", "value": "европейская"},
                                    {"label": "Итальянская", "value": "итальянская"},
                                    {"label": "Французская", "value": "французская"},
                                    {"label": "Кавказская", "value": "кавказская"},
                                ],
                                value="русская",
                                className="mb-3"
                            ),

                            html.Label("Название блюда:"),
                            dbc.Input(id="dish-input", type="text", placeholder="Например: борщ, окрошка, щи, уха...",
                                      className="mb-2"),
                            dbc.Button("Анализировать", id="rec-btn", color="primary", className="w-100 mb-3"),
                            html.Div(id="rec-output"),
                        ])
                    ])
                ], width=12)
            ])
        ]),

        dbc.Tab(label="Анализ меню (PDF)", children=[
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader("Загрузка меню ресторана",
                                       style={"backgroundColor": "#2E7D32", "borderRadius": "12px 12px 0 0",
                                              "color": "white"}),
                        dbc.CardBody([
                            html.P(
                                "Загрузите PDF-файл с вашим меню. Система проанализирует ингредиенты и подберет сезонные продукты.",
                                className="mb-3"),

                            dcc.Upload(
                                id="upload-pdf-menu",
                                children=html.Div([
                                    html.I(className="fas fa-cloud-upload-alt",
                                           style={"fontSize": "40px", "color": "#2E7D32"}),
                                    html.P("Перетащите файл сюда или нажмите для выбора",
                                           style={"marginTop": "10px"}),
                                    html.Small("Поддерживаются файлы PDF", className="text-muted")
                                ], className="upload-area"),
                                style={"width": "100%"},
                                multiple=False
                            ),

                            html.Div(id="pdf-upload-status", className="mt-3"),
                            html.Div(id="pdf-analysis-output", className="mt-4"),
                        ])
                    ])
                ], width=12)
            ])
        ]),
    ]),

    html.Hr(style={"borderColor": "#2E7D32", "opacity": "0.3"}),
    dbc.Row([
        dbc.Col(html.P("2026 Своё Шеф | Платформа от РСХБ", className="text-center",
                       style={"color": "#2E7D32", "fontSize": "12px"}))
    ], className="mt-3")
], fluid=True, className="px-4 py-3")


def create_price_chart(product):
    months = product['months']
    prices = product['price_timeline']
    current_month = datetime.now().month

    point_colors = ['#3b82f6' for _ in range(12)]
    point_colors[current_month - 1] = '#3b82f6'

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=months, y=prices, mode='lines+markers',
        line=dict(color='#3b82f6', width=2.5),
        marker=dict(size=6, color=point_colors, line=dict(color='white', width=1)),
        fill='tozeroy', fillcolor='rgba(59,130,246,0.08)'
    ))
    fig.update_layout(height=100, margin=dict(l=5, r=5, t=10, b=5),
                      plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                      xaxis=dict(showgrid=False, tickfont=dict(size=9, color="#666"), tickangle=0),
                      yaxis=dict(showgrid=False, showticklabels=False))
    return fig


def create_product_card(product, is_fav=False):
    fav_class = "btn-heart-fav" if is_fav else "btn-heart"
    fav_text = "❤️" if is_fav else "🤍"

    badges = []
    if product['premium']:
        badges.append(dbc.Badge("Премиум", className="me-1",
                                style={"fontSize": "10px", "backgroundColor": "#FFC107", "color": "#333",
                                       "borderRadius": "20px"}))
    if product['rare']:
        badges.append(dbc.Badge("Редкий", className="me-1",
                                style={"fontSize": "10px", "backgroundColor": "#f44336", "borderRadius": "20px"}))

    return dbc.Col([
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Badge(product['status'],
                                  style={"backgroundColor": product['status_color'], "fontSize": "10px",
                                         "borderRadius": "20px", "color": "white"},
                                  className="mb-1"),
                        html.H6(product['product_original'], className="mb-1 fw-bold",
                                style={"fontSize": "0.85rem", "color": "#2c3e50"}),
                        html.Small(f"{product['category']} | {product['farmer'][:20]}", className="text-muted",
                                   style={"fontSize": "11px"}),
                    ], width=8),
                    dbc.Col([
                        html.Div(badges, className="text-end mb-1"),
                        html.Strong(f"{product['current_price']} ₽", style={"color": "#2E7D32", "fontSize": "16px"}),
                        html.Small("/кг", className="text-muted", style={"fontSize": "10px"}),
                    ], width=4, className="text-end"),
                ]),
                dcc.Graph(figure=create_price_chart(product), config={'displayModeBar': False},
                          style={"height": "100px"}),
                dbc.Row([
                    dbc.Col(html.Small(product['region'], className="text-muted", style={"fontSize": "10px"}),
                            width=12),
                ]),
                html.Hr(className="my-1", style={"borderColor": "#eee"}),
                dbc.Row([
                    dbc.Col(dbc.Button(fav_text, id={"type": "fav", "index": product["product"]}, size="sm",
                                       className=fav_class), width="auto"),
                    dbc.Col([
                        dbc.Button("Фермер", href=product["farmer_url"], target="_blank", size="sm",
                                   style={"backgroundColor": "#2E7D32", "border": "none", "borderRadius": "20px",
                                          "fontSize": "11px", "color": "white", "padding": "4px 12px"},
                                   className="me-1"),
                        dbc.Button("Детали", href=product["url"], target="_blank", size="sm",
                                   style={"backgroundColor": "#2E7D32", "border": "none", "borderRadius": "20px",
                                          "fontSize": "11px", "color": "white", "padding": "4px 12px"}),
                    ], width="auto", className="text-end"),
                ], className="align-items-center justify-content-between")
            ], className="p-2")
        ], className="h-100 shadow-sm")
    ], width=12, md=6, lg=4, xl=3, className="mb-3")


def create_smart_recommendation_card(rec):
    if rec['found'] == True:
        return dbc.Card([
            dbc.CardBody([
                html.H5(f"Блюдо: {rec['dish_name'].capitalize()}", className="fw-bold text-success"),
                html.P(f"Кухня: {rec.get('cuisine', 'русская').capitalize()} | Сезон: {rec['current_season']}",
                       className="small text-muted"),
                html.Hr(),

                html.P("Ингредиенты:", className="fw-bold mb-1"),
                html.Ul([html.Li(ing, className="small") for ing in rec['ingredients']], className="mb-2"),

                html.P("Доступно сейчас:", className="fw-bold mb-1 mt-2"),
                html.Ul([
                    html.Li([
                        f"{item['name']} - в сезоне!",
                        html.Ul([
                            html.Li(html.A(f"{f['farmer']} ({f['region']}) - {f['current_price']} руб/кг",
                                           href=f['farmer_url'], target="_blank"), className="small")
                            for f in item['farmers'][:2]
                        ], className="mb-1") if item['farmers'] else html.Li("Фермеры не найдены",
                                                                             className="small text-muted")
                    ], className="mb-1") for item in rec['available'][:3]
                ], className="mb-2") if rec['available'] else html.P("Нет доступных ингредиентов",
                                                                     className="small text-muted"),

                html.P("Сезонные замены:", className="fw-bold mb-1 mt-2"),
                html.Ul([
                    html.Li([
                        f"Вместо {rep['original']} используйте {rep['replacement']}",
                        html.Ul([
                            html.Li(html.A(f"{f['farmer']} ({f['region']})", href=f['farmer_url'], target="_blank"),
                                    className="small")
                            for f in rep['farmers'][:2]
                        ], className="mb-1") if rep['farmers'] else html.Li("Фермеры не найдены",
                                                                            className="small text-muted")
                    ], className="mb-1") for rep in rec['replacements'][:3]
                ], className="mb-2") if rec['replacements'] else html.P("Нет замен", className="small text-muted"),

                html.Div(f"Совет шефу: {rec['advice']}", className="small text-success mt-2 p-2",
                         style={"backgroundColor": "#e8f5e9", "borderRadius": "8px"}),
            ])
        ], className="mb-3 shadow-sm", style={"borderRadius": "12px"})

    elif rec['found'] == "product_match":
        products_html = []
        for p in rec['matching_products'][:5]:
            products_html.append(
                html.Li(f"{p['product_original']} - {p['status']} от {p['farmer']} ({p['region']})", className="small"))

        return dbc.Card([
            dbc.CardBody([
                html.H5(f"Продукт: {rec['dish_name']}", className="fw-bold text-primary"),
                html.P(f"Кухня: {rec.get('cuisine', 'русская').capitalize()}", className="small text-muted"),
                html.P("Найден в каталоге фермеров:", className="fw-bold mb-1"),
                html.Ul(products_html, className="mb-2"),
                html.P(f"Сейчас сезон: {rec['current_season']}", className="small text-muted"),
            ])
        ], className="mb-3 shadow-sm", style={"borderRadius": "12px"})

    else:
        seasonal_html = []
        for p in rec.get('seasonal_products', []):
            seasonal_html.append(html.Li(f"{p['product_name']} - {p.get('description', '')}", className="small"))

        return dbc.Card([
            dbc.CardBody([
                html.H5(f"Блюдо: {rec['dish_name']}", className="fw-bold text-warning"),
                html.P(f"Кухня: {rec.get('cuisine', 'русская').capitalize()}", className="small text-muted"),
                html.P("Не найдено в базе. Вот что сейчас в сезоне:", className="mb-1"),
                html.Ul(seasonal_html if seasonal_html else [
                    html.Li("Загрузите файл seasonal_products.csv", className="small")], className="mb-2"),
                html.P("Попробуйте добавить эти продукты в меню!", className="small text-success"),
            ])
        ], className="mb-3 shadow-sm", style={"borderRadius": "12px"})


def create_pdf_analysis_card(analysis):
    if not analysis or not analysis.get("ingredients_found"):
        return dbc.Alert("Не удалось распознать ингредиенты из PDF. Попробуйте другой файл.", color="warning")

    products_html = []
    for p in analysis.get("products", [])[:10]:
        products_html.append(
            dbc.Row([
                dbc.Col(html.Strong(p['name']), width=5),
                dbc.Col(dbc.Badge(p['status'],
                                  style={"backgroundColor": "#2e7d32" if p['status'] == "В сезоне" else "#ed6c02"}),
                        width=3),
                dbc.Col(f"{p['price']} ₽/кг", width=2),
                dbc.Col(
                    html.A("Фермер", href=p['farmer_url'], target="_blank", className="btn btn-sm btn-outline-success"),
                    width=2),
            ], className="mb-2 border-bottom pb-2")
        )

    recommendations_html = []
    for r in analysis.get("recommendations", []):
        recommendations_html.append(html.Li(f"{r['name']} - {r['description']}", className="small"))

    return dbc.Card([
        dbc.CardBody([
            html.H5(f"Найдено ингредиентов: {len(analysis['ingredients_found'])}", className="text-success mb-3"),
            html.P("Ингредиенты из меню:", className="fw-bold"),
            html.Div(", ".join(analysis['ingredients_found'][:15]), className="small text-muted mb-3"),

            html.H6("Подходящие продукты от фермеров:", className="fw-bold mt-3"),
            html.Div(products_html if products_html else html.P("Нет совпадений", className="text-muted")),

            html.H6("Рекомендации на сезон:", className="fw-bold mt-3"),
            html.Ul(recommendations_html if recommendations_html else [html.Li("Нет рекомендаций", className="small")]),
        ])
    ], className="shadow-sm", style={"borderRadius": "12px"})


@app.callback(
    [Output("results-container", "children"),
     Output("search-status", "children"),
     Output("stats-badge", "children")],
    [Input("search-btn", "n_clicks"),
     Input("season-dropdown", "value"),
     Input("category-dropdown", "value"),
     Input("status-dropdown", "value"),
     Input("sort-dropdown", "value"),
     Input("fav-btn", "n_clicks"),
     Input("reset-filters", "n_clicks"),
     Input("favorites-store", "data")],
    [State("search-input", "value")]
)
def update_results(search_click, season_filter, category_filter, status_filter, sort_by, fav_click, reset_click,
                   fav_list, search_val):
    ctx = callback_context
    trigger = ctx.triggered[0]["prop_id"] if ctx.triggered else ""
    fav_list = fav_list or []

    if "reset" in trigger:
        search_val = ""
        season_filter = "all"
        category_filter = "all"
        status_filter = "all"
        sort_by = "default"

    filtered = products_db.copy()

    if "search-btn" in trigger and search_val and len(search_val) >= 2:
        fuzzy_ids = fuzzy_search(search_val, products_list)
        if fuzzy_ids:
            filtered = filtered[filtered["id"].isin(fuzzy_ids)]
            status_text = f"Найдено {len(filtered)} продуктов по запросу '{search_val}'"
        else:
            filtered = filtered.head(0)
            status_text = f"Ничего не найдено для '{search_val}'"
    elif "fav-btn" in trigger:
        filtered = filtered[filtered["product"].isin(fav_list)]
        status_text = f"Избранное: {len(filtered)} продуктов"
    else:
        if not search_val:
            filtered = filtered.head(24)
            status_text = f"Показано {len(filtered)} из {len(products_db)} продуктов"
        else:
            fuzzy_ids = fuzzy_search(search_val, products_list)
            if fuzzy_ids:
                filtered = filtered[filtered["id"].isin(fuzzy_ids)]
                status_text = f"Найдено {len(filtered)} продуктов"
            else:
                status_text = f"Показано {len(filtered.head(24))} продуктов"
                filtered = filtered.head(24)

        if season_filter == "in_season":
            filtered = filtered[filtered["status"] == "В сезоне"]
        elif season_filter == "soon":
            filtered = filtered[filtered["status"] == "Скоро"]
        elif season_filter == "out_season":
            filtered = filtered[filtered["status"] == "Не сезон"]

        if category_filter != "all":
            filtered = filtered[filtered["category"] == category_filter]

        if status_filter == "premium":
            filtered = filtered[filtered["premium"] == True]
        elif status_filter == "rare":
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

    stats_text = f"{len(products_db)} продуктов | {len(products_db[products_db['status'] == 'В сезоне'])} в сезоне"

    if filtered.empty:
        return html.Div(dbc.Alert("Ничего не найдено", color="info")), status_text, stats_text

    fav_set = set(fav_list)
    cards = dbc.Row(
        [create_product_card(row.to_dict(), row["product"] in fav_set) for _, row in filtered.head(48).iterrows()],
        className="g-3")
    return cards, status_text, stats_text


@app.callback(
    Output("favorites-store", "data", allow_duplicate=True),
    Input({"type": "fav", "index": dash.ALL}, "n_clicks"),
    State("favorites-store", "data"),
    prevent_initial_call=True
)
def toggle_favorite(clicks, fav_list):
    if not clicks or not any(clicks):
        return fav_list

    ctx = callback_context
    if not ctx.triggered:
        return fav_list

    import ast
    trigger = ctx.triggered[0]["prop_id"].split(".")[0]
    btn = ast.literal_eval(trigger)
    product = btn["index"]

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
    [Output("season-dropdown", "value"),
     Output("category-dropdown", "value"),
     Output("status-dropdown", "value"),
     Output("sort-dropdown", "value")],
    Input("reset-filters", "n_clicks"),
    prevent_initial_call=True
)
def reset_all_filters(n_clicks):
    return "all", "all", "all", "default"


@app.callback(
    Output("rec-output", "children"),
    Input("rec-btn", "n_clicks"),
    State("dish-input", "value"),
    State("cuisine-select", "value"),
    prevent_initial_call=True
)
def update_recommendation(n_clicks, dish_name, cuisine):
    if not dish_name:
        return dbc.Alert("Введите название блюда", color="warning")
    rec = get_smart_recommendation(dish_name, cuisine)
    if not rec:
        return dbc.Alert("Не удалось получить рекомендацию", color="info")
    return create_smart_recommendation_card(rec)


@app.callback(
    [Output("pdf-upload-status", "children"),
     Output("pdf-analysis-output", "children")],
    Input("upload-pdf-menu", "contents"),
    prevent_initial_call=True
)
def handle_pdf_upload(contents):
    if contents:
        ingredients = extract_ingredients_from_pdf(contents)
        if ingredients:
            analysis = analyze_pdf_menu(ingredients)
            return dbc.Alert(f"✓ PDF загружен. Найдено {len(ingredients)} ингредиентов", color="success",
                             className="small"), create_pdf_analysis_card(analysis)
        else:
            return dbc.Alert("Не удалось распознать ингредиенты из PDF. Попробуйте другой файл.", color="warning"), None
    return "", None


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("СВОЁ ШЕФ - ДАШБОРД ЗАПУЩЕН")
    print("=" * 50)
    print("Открыть: http://127.0.0.1:8050")
    print("=" * 50 + "\n")
    app.run(debug=True, port=8050)