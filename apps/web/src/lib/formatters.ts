/**
 * apps/web/src/lib/formatters.ts
 * ==============================
 * Formatting helpers for currency, APR percentages, dates, and Tailwind class merging.
 */

import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function formatCurrency(amount?: number | null, currency: string = "USD"): string {
  if (amount === undefined || amount === null || isNaN(amount)) return "$0.00";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

export function formatCompactCurrency(amount?: number | null): string {
  if (amount === undefined || amount === null || isNaN(amount)) return "$0";
  if (Math.abs(amount) >= 1_000_000) {
    return `$${(amount / 1_000_000).toFixed(1)}M`;
  }
  if (Math.abs(amount) >= 1_000) {
    return `$${(amount / 1_000).toFixed(0)}K`;
  }
  return formatCurrency(amount);
}

export function formatPercent(rate?: number | null): string {
  if (rate === undefined || rate === null || isNaN(rate)) return "0.00%";
  return `${rate.toFixed(2)}%`;
}

export function formatDate(dateStr?: string | null): string {
  if (!dateStr) return "N/A";
  try {
    const d = new Date(dateStr);
    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    }).format(d);
  } catch {
    return dateStr;
  }
}

export function formatExpiryCountdown(expiresAtTimestamp?: number | null): string {
  if (!expiresAtTimestamp) return "No expiration set";
  const now = Date.now() / 1000;
  const diffSec = expiresAtTimestamp - now;
  if (diffSec <= 0) return "EXPIRED";
  const hours = Math.floor(diffSec / 3600);
  const minutes = Math.floor((diffSec % 3600) / 60);
  return `${hours}h ${minutes}m remaining`;
}

