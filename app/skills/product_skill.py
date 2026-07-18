from app.tools.product import get_product_sales


def product_skill(message):

    data = get_product_sales(
        "SKU10086"
    )

    return {
        "type":"商品分析",
        "data":data
    }