const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "";

function buildApiUrl(path: string) {
  if (path.startsWith("http://") || path.startsWith("https://")) {
    return path;
  }

  return `${API_BASE_URL}${path}`;
}

async function readError(res: Response) {
  try {
    const body = await res.json();

    if (typeof body?.detail === "string") {
      return body.detail;
    }

    if (typeof body?.message === "string") {
      return body.message;
    }

    return JSON.stringify(body);
  } catch {
    return res.statusText || "Request failed";
  }
}

export type ProductCandidateStatus = "pending" | "approved" | "rejected" | string;

export type ProductCandidate = {
  id: number;
  source: string;
  source_type: string;
  source_url: string;
  merchant_name: string;
  brand_name: string | null;
  external_product_id: string;
  title: string;
  description: string | null;
  price_amount: string | null;
  currency: string | null;
  affiliate_url: string | null;
  merchant_url: string | null;
  image_url: string | null;
  availability: string | null;
  normalized_category: string | null;
  target_city_slug: string;
  city_connection_type?: string | null;
  city_connection_note?: string | null;
  haroona_score: number;
  score_reasons: string[];
  review_status: ProductCandidateStatus;
  review_notes: string | null;
  rejection_reason: string | null;
  promoted_product_id: number | null;
  created_at: string | null;
};

export type ProductCandidatesResponse = {
  items: ProductCandidate[];
  count: number;
};

export type CollectionScanRequest = {
  source_url: string;
  merchant_name: string;
  target_city_slug: string;
  normalized_category?: string | null;
  source?: string;
  source_type?: string;
  limit?: number;
};

export type CollectionScanResponse = {
  status: string;
  source_url: string;
  merchant_name: string;
  target_city_slug: string;
  found: number;
  created: number;
  updated: number;
  items?: Array<{
    external_product_id: string;
    title: string;
    price_amount: string | null;
    currency: string | null;
    merchant_url: string | null;
    image_url: string | null;
    availability: string | null;
    normalized_category: string | null;
    haroona_score: number;
    score_reasons: string[];
    review_notes: string | null;
  }>;
};

export type FetchProductCandidatesOptions = {
  status?: string;
  source?: string;
  targetCitySlug?: string;
  limit?: number;
  offset?: number;
};

export async function fetchProductCandidates({
  status = "pending",
  source,
  targetCitySlug,
  limit = 50,
  offset = 0,
}: FetchProductCandidatesOptions = {}): Promise<ProductCandidatesResponse> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });

  if (status) {
    params.set("status", status);
  }

  if (source) {
    params.set("source", source);
  }

  if (targetCitySlug) {
    params.set("target_city_slug", targetCitySlug);
  }

  const res = await fetch(
    buildApiUrl(`/admin/catalog/product-candidates?${params.toString()}`),
    {
      credentials: "include",
      cache: "no-store",
    },
  );

  if (!res.ok) {
    throw new Error(await readError(res));
  }

  const data = (await res.json()) as ProductCandidatesResponse;

  return {
    items: data.items ?? [],
    count: data.count ?? data.items?.length ?? 0,
  };
}

export async function runCollectionScan(
  payload: CollectionScanRequest,
): Promise<CollectionScanResponse> {
  const res = await fetch(buildApiUrl("/admin/catalog/collection-scan"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    throw new Error(await readError(res));
  }

  return (await res.json()) as CollectionScanResponse;
}

export async function approveProductCandidate(candidateId: number) {
  const res = await fetch(
    buildApiUrl(`/admin/catalog/product-candidates/${candidateId}/approve`),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ reviewed_by: "curator-studio" }),
    },
  );

  if (!res.ok) {
    throw new Error(await readError(res));
  }

  return res.json();
}

export async function rejectProductCandidate(candidateId: number, reason: string) {
  const res = await fetch(
    buildApiUrl(`/admin/catalog/product-candidates/${candidateId}/reject`),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ reviewed_by: "curator-studio", reason }),
    },
  );

  if (!res.ok) {
    throw new Error(await readError(res));
  }

  return res.json();
}
