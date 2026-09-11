CREATE TABLE product_cache (
                chain TEXT NOT NULL,
                query TEXT NOT NULL,
                zip TEXT NOT NULL,
                products_json TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (chain, query, zip)
            );
