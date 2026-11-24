import pandas as pd
import tiktoken

D = "/data/final/"
review = pd.read_csv(D + "olist_review_dataset_final.csv")
items = pd.read_csv(D + "olist_order_items_dataset_final.csv")
prod = pd.read_csv(D + "olist_product_dataset_final.csv")

df = review.merge(items, on="order_id", how="left").merge(prod, on="product_id", how="left")
df = df.dropna(subset=["product_category_name"])
df = df.drop_duplicates(subset=["review_id"]).reset_index(drop=True)
df = df[df["review_translate"].notna()]

print("Dokumen:", len(df))
print("Kategori Inggris NaN (bikin ingest lama crash):", int(df["product_category_name_english"].isna().sum()))
print("review_score NaN (bikin ingest lama crash):", int(df["review_score"].isna().sum()))

texts = [
    f"[product category: {str(c).strip()}] [review: {str(r).strip()}]"
    for c, r in zip(df["product_category_name_english"], df["review_translate"])
]

enc = tiktoken.get_encoding("cl100k_base")
lens = [len(enc.encode(t)) for t in texts]
total = sum(lens)
print("Total token:", total)
print("Rata-rata per dokumen:", round(total / len(lens), 1), "| maks:", max(lens))
print("Dokumen > 8191 token:", sum(1 for n in lens if n > 8191))
print("Estimasi biaya @ $0.02 per 1M token: $%.4f" % (total / 1e6 * 0.02))
