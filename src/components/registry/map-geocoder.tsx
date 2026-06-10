"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useGeocode, type GeocodeSuggestion } from "@/hooks/use-geocode";

interface MapGeocoderProps {
  onSelect: (suggestion: GeocodeSuggestion) => void;
}

export function MapGeocoder({ onSelect }: MapGeocoderProps) {
  const t = useTranslations("registry.map");

  const [searchValue, setSearchValue] = useState("");
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const [isFocused, setIsFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const { suggestions, isLoading, clear } = useGeocode(searchValue);

  // Derived from focus + results so we never set "open" state inside an effect.
  const isOpen = isFocused && suggestions.length > 0;

  const handleSelect = useCallback(
    (suggestion: GeocodeSuggestion) => {
      onSelect(suggestion);
      setSearchValue(suggestion.name);
      setHighlightedIndex(-1);
      clear();
      inputRef.current?.blur();
    },
    [onSelect, clear],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (suggestions.length === 0) return;

      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setHighlightedIndex((prev) =>
            prev < suggestions.length - 1 ? prev + 1 : 0,
          );
          break;
        case "ArrowUp":
          e.preventDefault();
          setHighlightedIndex((prev) =>
            prev > 0 ? prev - 1 : suggestions.length - 1,
          );
          break;
        case "Enter":
          e.preventDefault();
          if (highlightedIndex >= 0 && suggestions[highlightedIndex]) {
            handleSelect(suggestions[highlightedIndex]);
          }
          break;
        case "Escape":
          setHighlightedIndex(-1);
          inputRef.current?.blur();
          break;
      }
    },
    [suggestions, highlightedIndex, handleSelect],
  );

  useEffect(() => {
    if (highlightedIndex >= 0 && listRef.current) {
      const item = listRef.current.children[highlightedIndex] as HTMLElement;
      item?.scrollIntoView({ block: "nearest" });
    }
  }, [highlightedIndex]);

  return (
    <div className="relative w-[260px] max-w-[calc(100vw-2rem)]">
      <input
        ref={inputRef}
        type="text"
        dir="auto"
        value={searchValue}
        onChange={(e) => {
          setSearchValue(e.target.value);
          setHighlightedIndex(-1);
        }}
        onKeyDown={handleKeyDown}
        onFocus={() => setIsFocused(true)}
        onBlur={() => {
          // Delay so a suggestion click registers before the list unmounts.
          setTimeout(() => setIsFocused(false), 150);
        }}
        placeholder={t("searchPlaceholder")}
        aria-label={t("searchLabel")}
        role="combobox"
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        aria-controls="map-geocoder-suggestions"
        autoComplete="off"
        className="w-full bg-p-paper border border-p-line rounded-[var(--p-r-md)] px-3 py-2 text-small text-p-ink placeholder:text-p-ink-3 shadow-[var(--p-shadow-md)] focus:outline-none focus:border-p-primary transition-colors"
      />
      {isLoading && (
        <span className="absolute end-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 rounded-full border-2 border-p-line border-t-p-primary animate-spin" />
      )}

      {isOpen && suggestions.length > 0 && (
        <ul
          ref={listRef}
          id="map-geocoder-suggestions"
          role="listbox"
          className="absolute z-10 mt-1 w-full max-h-60 overflow-auto bg-p-paper border border-p-line rounded-[var(--p-r-md)] shadow-[var(--p-shadow-md)]"
        >
          {suggestions.map((suggestion, index) => (
            <li
              key={suggestion.id}
              role="option"
              aria-selected={index === highlightedIndex}
              dir="auto"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => handleSelect(suggestion)}
              onMouseEnter={() => setHighlightedIndex(index)}
              className={`px-3 py-2 cursor-pointer transition-colors ${
                index === highlightedIndex ? "bg-p-bg-soft" : "hover:bg-p-bg-soft"
              }`}
            >
              <div className="text-small text-p-ink truncate">
                {suggestion.name}
              </div>
              <div className="text-micro text-p-ink-3 truncate">
                {suggestion.displayName}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
