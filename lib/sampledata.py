"""Names and value lists of the Kibana sample datasets, for writing tasks.

The datasets are fixed (only their timestamps move to the install date), so
values picked from these lists always match a sensible number of documents.
"""

ECOMMERCE = "kibana_sample_data_ecommerce"
FLIGHTS = "kibana_sample_data_flights"
LOGS = "kibana_sample_data_logs"     # a data stream

ECOMMERCE_CATEGORIES = {
    "FEMALE": ["Women's Clothing", "Women's Shoes", "Women's Accessories"],
    "MALE": ["Men's Clothing", "Men's Shoes", "Men's Accessories"],
}
ALL_CATEGORIES = [c for cs in ECOMMERCE_CATEGORIES.values() for c in cs]
MANUFACTURERS = ["Low Tide Media", "Elitelligence", "Oceanavigations", "Tigress Enterprises",
                 "Pyramidustries", "Angeldale", "Gnomehouse", "Spherecords", "Microlutions"]
CONTINENTS = ["Asia", "North America", "Europe", "Africa"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
LAST_NAMES = ["Perkins", "Underwood", "Rivera", "Graham", "Foster", "Gregory", "Bryant", "Marshall",
              "Mccarthy", "Goodwin", "Padilla", "Summers", "Fletcher", "Hodges"]
# Product names look like "Ankle boots - black": (first word, last word, words in between)
PRODUCT_PHRASES = [("ankle", "black", 1), ("summer", "black", 1), ("jersey", "black", 1),
                   ("lace", "black", 2), ("lace", "coffee", 3), ("print", "white", 2),
                   ("high", "black", 2), ("tracksuit", "black", 1), ("ankle", "cognac", 1)]
PRODUCT_WORDS = ["boots", "dress", "jacket", "trainers", "bag", "jumper", "shirt", "coat"]
COLORS = ["black", "white", "blue", "cognac", "red", "grey"]

FLIGHT_CARRIERS = ["Logstash Airways", "JetBeats", "Kibana Airlines", "ES-Air"]
FLIGHT_WEATHER = ["Rain", "Clear", "Sunny", "Cloudy", "Heavy Fog", "Thunder & Lightning", "Damaging Wind",
                  "Hail"]
FLIGHT_COUNTRIES = ["IT", "US", "CN", "CA", "JP", "RU", "CH", "GB", "AU", "PL", "AT", "IN"]
FLIGHT_CITIES = ["Zurich", "Xi'an", "Shanghai", "Winnipeg", "Tokyo", "Warsaw", "Verona", "Vienna",
                 "Venice", "London", "Buenos Aires", "Sydney"]

LOG_EXTENSIONS = ["gz", "css", "zip", "deb", "rpm"]
LOG_OS = ["win xp", "osx", "win 7", "win 8", "ios"]
LOG_TAGS = ["security", "warning", "error", "login"]
LOG_PRODUCTS = ["kibana", "beats", "elasticsearch", "apm"]
