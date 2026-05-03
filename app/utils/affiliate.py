def is_affiliate(url: str) -> bool:
    if not url:
        return False

    url = url.lower()

    affiliate_domains = [
        "awin1.com",
        "cj.com",
        "linksynergy.com",
        "rakuten.com",
        "tkqlhce.com",
        "jdoqocy.com",
        "anrdoezrs.net",
        "ktk"
    ]

    return any(domain in url for domain in affiliate_domains)