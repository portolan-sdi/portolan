"use client";

import { useState, useEffect, useRef, useCallback } from "react";

export interface GeocodeSuggestion {
  id: string;
  name: string;
  displayName: string;
  lat: number;
  lng: number;
  // Nominatim bounding box, normalized to [west, south, east, north] numbers.
  bbox?: [number, number, number, number];
}

interface NominatimResult {
  place_id: number;
  display_name: string;
  lat: string;
  lon: string;
  name?: string;
  // Nominatim returns [south, north, west, east] as strings.
  boundingbox?: [string, string, string, string];
}

const geocodeCache = new Map<string, GeocodeSuggestion[]>();
const CACHE_MAX_SIZE = 50;

const NOMINATIM_URL =
  process.env.NEXT_PUBLIC_NOMINATIM_URL || "https://nominatim.openstreetmap.org";

export function useGeocode(query: string, debounceMs = 300) {
  const [suggestions, setSuggestions] = useState<GeocodeSuggestion[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const search = useCallback(async (searchQuery: string) => {
    abortRef.current?.abort();
    abortRef.current = new AbortController();

    const trimmed = searchQuery.trim().toLowerCase();
    if (!trimmed || trimmed.length < 2) {
      setSuggestions([]);
      setIsLoading(false);
      return;
    }

    const cached = geocodeCache.get(trimmed);
    if (cached) {
      setSuggestions(cached);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams({
        q: searchQuery,
        format: "json",
        addressdetails: "1",
        limit: "5",
      });

      const response = await fetch(`${NOMINATIM_URL}/search?${params}`, {
        signal: abortRef.current.signal,
      });

      if (!response.ok) {
        throw new Error(`Nominatim error: ${response.status}`);
      }

      const results: NominatimResult[] = await response.json();

      const mapped: GeocodeSuggestion[] = results.map((r) => {
        let bbox: [number, number, number, number] | undefined;
        if (r.boundingbox && r.boundingbox.length === 4) {
          const [south, north, west, east] = r.boundingbox.map(parseFloat);
          if (![south, north, west, east].some(Number.isNaN)) {
            bbox = [west, south, east, north];
          }
        }
        return {
          id: String(r.place_id),
          name: r.name || r.display_name.split(",")[0],
          displayName: r.display_name,
          lat: parseFloat(r.lat),
          lng: parseFloat(r.lon),
          bbox,
        };
      });

      if (geocodeCache.size >= CACHE_MAX_SIZE) {
        const firstKey = geocodeCache.keys().next().value;
        if (firstKey) geocodeCache.delete(firstKey);
      }
      geocodeCache.set(trimmed, mapped);

      setSuggestions(mapped);
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        return;
      }
      setError(err instanceof Error ? err.message : "Search failed");
      setSuggestions([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }

    timeoutRef.current = setTimeout(() => {
      search(query);
    }, debounceMs);

    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, [query, debounceMs, search]);

  const clear = useCallback(() => {
    setSuggestions([]);
    setError(null);
  }, []);

  return { suggestions, isLoading, error, clear };
}
