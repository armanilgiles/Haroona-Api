"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  CheckCircle2,
  CircleDashed,
  ClipboardList,
  ExternalLink,
  Loader2,
  RefreshCw,
  Search,
  Sparkles,
  Store,
  Wand2,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  approveProductCandidate,
  fetchProductCandidates,
  type CollectionScanResponse,
  type ProductCandidate,
  rejectProductCandidate,
  runCollectionScan,
} from "@/lib/admin-curation";

const DEFAULT_SOURCE_URL = "https://www.nobodyschild.com/en-us/collections/materra";
const DEFAULT_MERCHANT = "Nobody's Child";
const DEFAULT_CITY = "london";

const pipeline = [
  {
    title: "Find products",
    description: "Pull candidates from approved brands, boutiques, and feeds.",
    icon: Search,
  },
  {
    title: "Score the fit",
    description: "Rate by city, category, image quality, price, and Haroona mood.",
    icon: Wand2,
  },
  {
    title: "Curator decision",
    description: "Accept, reject, or send back for a second look before publishing.",
    icon: ClipboardList,
  },
  {
    title: "Publish to Haroona",
    description: "Approved pieces appear in discovery and start feeding analytics.",
    icon: Store,
  },
];

function StudioPanel({
  children,
  className,
  id,
}: {
  children: React.ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section
      id={id}
      className={cn(
        "rounded-[1.75rem] border border-white/80 bg-white/85 p-5 shadow-sm shadow-[#d7c6b6]/30 backdrop-blur-xl",
        className,
      )}
    >
      {children}
    </section>
  );
}

function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const classes =
    normalized === "approved"
      ? "bg-emerald-50 text-emerald-700 ring-emerald-100"
      : normalized === "rejected"
        ? "bg-rose-50 text-rose-700 ring-rose-100"
        : "bg-amber-50 text-amber-700 ring-amber-100";

  const label = normalized.charAt(0).toUpperCase() + normalized.slice(1);

  return (
    <span
      className={cn(
        "inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ring-1",
        classes,
      )}
    >
      {label}
    </span>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="rounded-3xl border border-dashed border-[#eadfd5] bg-[#fbf7f3] px-4 py-10 text-center">
      <Sparkles className="mx-auto h-8 w-8 text-violet-500" />
      <p className="mt-3 text-sm font-semibold text-slate-800">{message}</p>
      <p className="mt-1 text-xs text-slate-500">
        Run a source scan to fill this queue with real product candidates.
      </p>
    </div>
  );
}

function formatPrice(candidate: ProductCandidate) {
  if (!candidate.price_amount) return "—";

  const amount = Number(candidate.price_amount);
  if (Number.isNaN(amount)) return candidate.price_amount;

  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: candidate.currency || "USD",
  }).format(amount);
}

function formatCitySlug(slug: string) {
  return slug
    .split("-")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}


function formatReason(reason: string) {
  const cleaned = reason.replace(/[_-]/g, " ").trim();
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

function formatConnectionLabel(type?: string | null) {
  if (!type) return null;

  return type
    .replace(/[_-]/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function getScoreLabel(score: number) {
  if (score >= 85) return "Strong fit";
  if (score >= 70) return "Good fit";
  if (score >= 55) return "Possible fit";
  return "Weak fit";
}

function getScoreBarClass(score: number) {
  if (score >= 85) return "bg-emerald-500";
  if (score >= 70) return "bg-violet-500";
  if (score >= 55) return "bg-amber-500";
  return "bg-rose-400";
}

function ScoreReasoning({ candidate }: { candidate: ProductCandidate }) {
  const reasons = candidate.score_reasons ?? [];
  const visibleReasons = reasons.slice(0, 6);
  const hiddenReasonCount = Math.max(reasons.length - visibleReasons.length, 0);
  const connectionLabel = formatConnectionLabel(candidate.city_connection_type);

  if (!visibleReasons.length && !connectionLabel && !candidate.city_connection_note) {
    return null;
  }

  return (
    <div className="rounded-3xl border border-violet-100 bg-violet-50/70 px-4 py-3 md:col-span-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Sparkles className="h-3.5 w-3.5 text-violet-600" />
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-violet-700">
            Why this scored {candidate.haroona_score}
          </p>
        </div>
        {connectionLabel ? (
          <span className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-violet-700 ring-1 ring-violet-100">
            {connectionLabel}
          </span>
        ) : null}
      </div>

      {candidate.city_connection_note ? (
        <p className="mt-2 text-xs leading-5 text-violet-900/75">
          {candidate.city_connection_note}
        </p>
      ) : null}

      {visibleReasons.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {visibleReasons.map((reason) => (
            <span
              key={reason}
              className="rounded-full bg-white px-2.5 py-1 text-xs font-medium text-slate-700 ring-1 ring-violet-100"
            >
              {formatReason(reason)}
            </span>
          ))}
          {hiddenReasonCount > 0 ? (
            <span className="rounded-full bg-violet-100 px-2.5 py-1 text-xs font-semibold text-violet-700">
              +{hiddenReasonCount} more
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function CandidateActions({
  candidate,
  isBusy,
  onApprove,
  onReject,
}: {
  candidate: ProductCandidate;
  isBusy: boolean;
  onApprove: (candidate: ProductCandidate) => void;
  onReject: (candidate: ProductCandidate) => void;
}) {
  if (candidate.review_status !== "pending") {
    return null;
  }

  return (
    <div className="mt-3 flex flex-wrap gap-2 md:mt-0 md:justify-end">
      <button
        type="button"
        disabled={isBusy}
        onClick={() => onApprove(candidate)}
        className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-emerald-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {isBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
        Approve
      </button>
      <button
        type="button"
        disabled={isBusy}
        onClick={() => onReject(candidate)}
        className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-rose-50 px-3 py-2 text-xs font-semibold text-rose-700 ring-1 ring-rose-100 transition hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60"
      >
        Reject
      </button>
    </div>
  );
}

export function CuratorStudioDashboard() {
  const [sourceUrl, setSourceUrl] = useState(DEFAULT_SOURCE_URL);
  const [merchantName, setMerchantName] = useState(DEFAULT_MERCHANT);
  const [targetCitySlug, setTargetCitySlug] = useState(DEFAULT_CITY);
  const [normalizedCategory, setNormalizedCategory] = useState("dresses");
  const [scanLimit, setScanLimit] = useState(25);
  const [queueStatus, setQueueStatus] = useState("pending");
  const [candidates, setCandidates] = useState<ProductCandidate[]>([]);
  const [lastScan, setLastScan] = useState<CollectionScanResponse | null>(null);
  const [isLoadingQueue, setIsLoadingQueue] = useState(true);
  const [isScanning, setIsScanning] = useState(false);
  const [busyCandidateId, setBusyCandidateId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadCandidates = useCallback(async () => {
    setIsLoadingQueue(true);
    setError(null);

    try {
      const data = await fetchProductCandidates({
        status: queueStatus,
        targetCitySlug: targetCitySlug || undefined,
        limit: 75,
      });
      setCandidates(data.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load product queue");
    } finally {
      setIsLoadingQueue(false);
    }
  }, [queueStatus, targetCitySlug]);

  useEffect(() => {
    void loadCandidates();
  }, [loadCandidates]);

  const queueStats = useMemo(
    () => [
      {
        label: "Visible candidates",
        value: String(candidates.length),
        helper: `${queueStatus} queue for ${formatCitySlug(targetCitySlug)}`,
      },
      {
        label: "Last scan found",
        value: lastScan ? String(lastScan.found) : "—",
        helper: lastScan ? `${lastScan.created} new · ${lastScan.updated} updated` : "run a source scan",
      },
      {
        label: "Top score",
        value: candidates.length
          ? String(Math.max(...candidates.map((item) => item.haroona_score)))
          : "—",
        helper: "highest Haroona fit score",
      },
      {
        label: "Ready to publish",
        value: queueStatus === "approved" ? String(candidates.length) : "—",
        helper: "publish step comes next",
      },
    ],
    [candidates, lastScan, queueStatus, targetCitySlug],
  );

  async function handleRunScan(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsScanning(true);
    setError(null);

    try {
      const result = await runCollectionScan({
        source_url: sourceUrl.trim(),
        merchant_name: merchantName.trim(),
        target_city_slug: targetCitySlug.trim(),
        normalized_category: normalizedCategory.trim() || null,
        source: "shopify",
        source_type: "collection",
        limit: scanLimit,
      });

      setLastScan(result);
      setQueueStatus("pending");

      const refreshed = await fetchProductCandidates({
        status: "pending",
        targetCitySlug: targetCitySlug.trim() || undefined,
        limit: 75,
      });
      setCandidates(refreshed.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Collection scan failed");
    } finally {
      setIsScanning(false);
    }
  }

  async function handleApprove(candidate: ProductCandidate) {
    setBusyCandidateId(candidate.id);
    setError(null);

    try {
      await approveProductCandidate(candidate.id);
      await loadCandidates();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to approve candidate");
    } finally {
      setBusyCandidateId(null);
    }
  }

  async function handleReject(candidate: ProductCandidate) {
    const reason = window.prompt("Why are you rejecting this product?", "Not a Haroona fit");
    if (!reason) return;

    setBusyCandidateId(candidate.id);
    setError(null);

    try {
      await rejectProductCandidate(candidate.id, reason);
      await loadCandidates();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reject candidate");
    } finally {
      setBusyCandidateId(null);
    }
  }

  return (
    <div className="mx-auto max-w-[1500px] space-y-6">
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(360px,0.9fr)]">
        <div className="rounded-[2rem] bg-[#11101f] p-6 text-white shadow-2xl shadow-slate-950/10 sm:p-8">
          <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.22em] text-white/65">
            <Sparkles className="h-3.5 w-3.5" />
            Curator Studio
          </div>
          <h1 className="mt-5 max-w-2xl text-3xl font-semibold tracking-[-0.05em] sm:text-5xl">
            Scan collections, rank candidates, and approve only the best pieces.
          </h1>
          <p className="mt-4 max-w-2xl text-sm leading-6 text-white/55 sm:text-base">
            This is now wired to the FastAPI curation backend. Run a Shopify
            collection scan, save draft candidates, then review the queue before
            anything hits the live Haroona grid.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <a
              href="#products"
              className="inline-flex items-center gap-2 rounded-2xl bg-white px-4 py-2.5 text-sm font-semibold text-slate-950 transition hover:bg-[#f6efe7]"
            >
              Review queue
              <ArrowRight className="h-4 w-4" />
            </a>
            <a
              href="#source-scan"
              className="inline-flex items-center gap-2 rounded-2xl border border-white/10 bg-white/10 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-white/15"
            >
              Add product source
              <ExternalLink className="h-4 w-4" />
            </a>
          </div>
        </div>

        <StudioPanel>
          <p className="text-lg font-semibold tracking-[-0.03em] text-slate-950">
            Curation snapshot
          </p>
          <p className="mt-1 text-sm text-slate-500">
            Live numbers from the product candidate queue.
          </p>
          <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
            {queueStats.map((stat) => (
              <div
                key={stat.label}
                className="rounded-3xl border border-[#efe6dd] bg-[#fbf7f3] p-4"
              >
                <p className="text-sm font-medium text-slate-500">{stat.label}</p>
                <p className="mt-2 text-3xl font-semibold tracking-[-0.05em] text-slate-950">
                  {stat.value}
                </p>
                <p className="mt-1 text-xs text-slate-400">{stat.helper}</p>
              </div>
            ))}
          </div>
        </StudioPanel>
      </div>

      {error ? (
        <div className="rounded-3xl border border-rose-100 bg-rose-50 px-5 py-4 text-sm font-medium text-rose-700">
          {error}
        </div>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[minmax(360px,0.8fr)_minmax(0,1.2fr)]">
        <div className="space-y-6">
          <StudioPanel id="source-scan">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-lg font-semibold tracking-[-0.03em] text-slate-950">
                  Source scan
                </p>
                <p className="mt-1 text-sm text-slate-500">
                  Start with one collection URL and let FastAPI create draft products.
                </p>
              </div>
              {isScanning ? (
                <Loader2 className="h-5 w-5 animate-spin text-violet-500" />
              ) : (
                <Search className="h-5 w-5 text-violet-500" />
              )}
            </div>

            <form onSubmit={handleRunScan} className="mt-6 space-y-4">
              <label className="block text-sm font-semibold text-slate-700">
                Collection URL
                <input
                  value={sourceUrl}
                  onChange={(event) => setSourceUrl(event.target.value)}
                  className="mt-2 w-full rounded-2xl border border-[#eadfd5] bg-white px-4 py-3 text-sm font-medium text-slate-900 outline-none transition focus:border-violet-300 focus:ring-4 focus:ring-violet-100"
                  placeholder="https://www.nobodyschild.com/en-us/collections/materra"
                  required
                />
              </label>

              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block text-sm font-semibold text-slate-700">
                  Merchant
                  <input
                    value={merchantName}
                    onChange={(event) => setMerchantName(event.target.value)}
                    className="mt-2 w-full rounded-2xl border border-[#eadfd5] bg-white px-4 py-3 text-sm font-medium text-slate-900 outline-none transition focus:border-violet-300 focus:ring-4 focus:ring-violet-100"
                    required
                  />
                </label>

                <label className="block text-sm font-semibold text-slate-700">
                  City slug
                  <input
                    value={targetCitySlug}
                    onChange={(event) => setTargetCitySlug(event.target.value)}
                    className="mt-2 w-full rounded-2xl border border-[#eadfd5] bg-white px-4 py-3 text-sm font-medium text-slate-900 outline-none transition focus:border-violet-300 focus:ring-4 focus:ring-violet-100"
                    placeholder="london"
                    required
                  />
                </label>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block text-sm font-semibold text-slate-700">
                  Category hint
                  <input
                    value={normalizedCategory}
                    onChange={(event) => setNormalizedCategory(event.target.value)}
                    className="mt-2 w-full rounded-2xl border border-[#eadfd5] bg-white px-4 py-3 text-sm font-medium text-slate-900 outline-none transition focus:border-violet-300 focus:ring-4 focus:ring-violet-100"
                    placeholder="dresses"
                  />
                </label>

                <label className="block text-sm font-semibold text-slate-700">
                  Limit
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={scanLimit}
                    onChange={(event) => setScanLimit(Number(event.target.value))}
                    className="mt-2 w-full rounded-2xl border border-[#eadfd5] bg-white px-4 py-3 text-sm font-medium text-slate-900 outline-none transition focus:border-violet-300 focus:ring-4 focus:ring-violet-100"
                  />
                </label>
              </div>

              <button
                type="submit"
                disabled={isScanning}
                className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-[#11101f] px-4 py-3 text-sm font-semibold text-white shadow-lg shadow-slate-950/10 transition hover:bg-[#1b1830] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isScanning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                {isScanning ? "Scanning collection..." : "Run collection scan"}
              </button>
            </form>

            {lastScan ? (
              <div className="mt-5 rounded-3xl border border-violet-100 bg-violet-50 px-4 py-3 text-sm text-violet-900">
                <p className="font-semibold">Last scan complete</p>
                <p className="mt-1 text-violet-800/80">
                  Found {lastScan.found} candidates · {lastScan.created} new · {lastScan.updated} updated.
                </p>
              </div>
            ) : null}
          </StudioPanel>

          <StudioPanel>
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-lg font-semibold tracking-[-0.03em] text-slate-950">
                  Workflow
                </p>
                <p className="mt-1 text-sm text-slate-500">
                  Backend scans. Curate Studio reviews.
                </p>
              </div>
              <CircleDashed className="h-5 w-5 text-violet-500" />
            </div>

            <div className="mt-6 space-y-4">
              {pipeline.map((step, index) => {
                const Icon = step.icon;

                return (
                  <div key={step.title} className="flex gap-4">
                    <div className="flex flex-col items-center">
                      <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-violet-50 text-violet-700 ring-1 ring-violet-100">
                        <Icon className="h-5 w-5" />
                      </div>
                      {index !== pipeline.length - 1 ? (
                        <div className="mt-2 h-10 w-px bg-[#eadfd5]" />
                      ) : null}
                    </div>
                    <div className="pt-1">
                      <p className="text-sm font-semibold text-slate-950">
                        {step.title}
                      </p>
                      <p className="mt-1 text-sm leading-5 text-slate-500">
                        {step.description}
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
          </StudioPanel>
        </div>

        <StudioPanel id="products">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="text-lg font-semibold tracking-[-0.03em] text-slate-950">
                Product review queue
              </p>
              <p className="mt-1 text-sm text-slate-500">
                Real product candidates from FastAPI. Approve/reject before publishing.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {['pending', 'approved', 'rejected'].map((status) => (
                <button
                  key={status}
                  type="button"
                  onClick={() => setQueueStatus(status)}
                  className={cn(
                    "rounded-2xl px-3 py-2 text-xs font-semibold ring-1 transition",
                    queueStatus === status
                      ? "bg-[#11101f] text-white ring-[#11101f]"
                      : "bg-white text-slate-600 ring-[#eadfd5] hover:bg-[#fbf7f3]",
                  )}
                >
                  {status.charAt(0).toUpperCase() + status.slice(1)}
                </button>
              ))}
              <button
                type="button"
                onClick={() => void loadCandidates()}
                className="inline-flex items-center justify-center gap-2 rounded-2xl bg-white px-3 py-2 text-xs font-semibold text-slate-600 ring-1 ring-[#eadfd5] transition hover:bg-[#fbf7f3]"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Refresh
              </button>
            </div>
          </div>

          <div className="mt-6 overflow-hidden rounded-3xl border border-[#eadfd5] bg-white">
            <div className="hidden grid-cols-[1.4fr_0.7fr_0.7fr_0.6fr_0.55fr_0.95fr] gap-4 border-b border-[#eadfd5] bg-[#fbf7f3] px-4 py-3 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400 md:grid">
              <span>Product</span>
              <span>Brand</span>
              <span>City</span>
              <span>Score</span>
              <span>Status</span>
              <span className="text-right">Actions</span>
            </div>

            {isLoadingQueue ? (
              <div className="flex items-center justify-center gap-3 px-4 py-12 text-sm font-semibold text-slate-500">
                <Loader2 className="h-5 w-5 animate-spin text-violet-500" />
                Loading product queue...
              </div>
            ) : candidates.length === 0 ? (
              <div className="p-4">
                <EmptyState message="No candidates in this queue yet." />
              </div>
            ) : (
              <div className="divide-y divide-[#f0e7df]">
                {candidates.map((item) => (
                  <div
                    key={item.id}
                    className="grid gap-3 px-4 py-4 md:grid-cols-[1.4fr_0.7fr_0.7fr_0.6fr_0.55fr_0.95fr] md:items-center md:gap-4"
                  >
                    <div className="flex gap-3">
                      <div className="h-16 w-12 shrink-0 overflow-hidden rounded-2xl bg-[#f4ede5]">
                        {item.image_url ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={item.image_url}
                            alt={item.title}
                            className="h-full w-full object-cover"
                          />
                        ) : null}
                      </div>
                      <div className="min-w-0">
                        <p className="line-clamp-2 text-sm font-semibold text-slate-950">
                          {item.title}
                        </p>
                        <p className="mt-1 text-xs font-medium text-slate-500">
                          {formatPrice(item)} · {item.normalized_category ?? "uncategorized"}
                        </p>
                        {item.merchant_url ? (
                          <a
                            href={item.merchant_url}
                            target="_blank"
                            rel="noreferrer"
                            className="mt-1 inline-flex items-center gap-1 text-xs font-semibold text-slate-400 transition hover:text-violet-600"
                          >
                            View source <ExternalLink className="h-3 w-3" />
                          </a>
                        ) : null}
                      </div>
                    </div>
                    <p className="hidden text-sm text-slate-600 md:block">
                      {item.brand_name || item.merchant_name}
                    </p>
                    <p className="hidden text-sm text-slate-600 md:block">
                      {formatCitySlug(item.target_city_slug)}
                    </p>
                    <div className="space-y-1.5">
                      <div className="flex items-center gap-2">
                        <div className="h-2 w-24 overflow-hidden rounded-full bg-slate-100 md:w-16">
                          <div
                            className={cn("h-full rounded-full", getScoreBarClass(item.haroona_score))}
                            style={{ width: `${item.haroona_score}%` }}
                          />
                        </div>
                        <span className="text-sm font-semibold text-slate-950">
                          {item.haroona_score}
                        </span>
                      </div>
                      <p className="text-xs font-semibold text-slate-400">
                        {getScoreLabel(item.haroona_score)}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <StatusBadge status={item.review_status} />
                      {item.review_status === "approved" ? (
                        <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                      ) : item.review_status === "rejected" ? (
                        <XCircle className="h-4 w-4 text-rose-500" />
                      ) : null}
                    </div>
                    <CandidateActions
                      candidate={item}
                      isBusy={busyCandidateId === item.id}
                      onApprove={handleApprove}
                      onReject={handleReject}
                    />
                    <ScoreReasoning candidate={item} />
                  </div>
                ))}
              </div>
            )}
          </div>
        </StudioPanel>
      </div>
    </div>
  );
}
