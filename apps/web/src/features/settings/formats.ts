import type { Preferences } from "@wiredex/api-client";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { usePreferences } from "./preferences";

export type DateFormat = Preferences["date_format"];
export type NumberFormat = Preferences["number_format"];

/** How a page writes dates and numbers, by the workspace's settings (spec 25). */
export type Formats = {
  /** A day: `11 Oct 2026` in the reader's language, or `2026-10-11` and the like. */
  date: (value: string | Date) => string;
  /** A day and the time to the minute. */
  dateTime: (value: string | Date) => string;
  number: (value: number, options?: Intl.NumberFormatOptions) => string;
  /** The locale numbers are written in, for a formatter of its own. */
  numberLocale: string;
};

/** What `point` and `comma` write numbers as, whatever the language. */
const NUMBER_LOCALE: Record<Exclude<NumberFormat, "language">, string> = {
  point: "en-US",
  comma: "pt-BR",
};

const two = (value: number) => String(value).padStart(2, "0");

/** A day in one of the fixed orders, from the reader's own clock. */
function fixedDate(date: Date, format: Exclude<DateFormat, "language">): string {
  const [year, month, day] = [date.getFullYear(), two(date.getMonth() + 1), two(date.getDate())];
  if (format === "iso") return `${year}-${month}-${day}`;
  return format === "dmy" ? `${day}/${month}/${year}` : `${month}/${day}/${year}`;
}

export function formatsOf(
  language: string,
  dateFormat: DateFormat = "language",
  numberFormat: NumberFormat = "language",
): Formats {
  const numberLocale = numberFormat === "language" ? language : NUMBER_LOCALE[numberFormat];
  const day = new Intl.DateTimeFormat(language, { dateStyle: "medium" });
  const dayAndTime = new Intl.DateTimeFormat(language, { dateStyle: "medium", timeStyle: "short" });
  const asDate = (value: string | Date) => (value instanceof Date ? value : new Date(value));
  return {
    date: (value) =>
      dateFormat === "language" ? day.format(asDate(value)) : fixedDate(asDate(value), dateFormat),
    dateTime: (value) => {
      const date = asDate(value);
      if (dateFormat === "language") return dayAndTime.format(date);
      // A fixed order keeps a 24-hour clock, as the formats it copies do.
      return `${fixedDate(date, dateFormat)} ${two(date.getHours())}:${two(date.getMinutes())}`;
    },
    number: (value, options) => new Intl.NumberFormat(numberLocale, options).format(value),
    numberLocale,
  };
}

/** The formats of the workspace's settings; the language's own until they are read. */
export function useFormats(): Formats {
  const { i18n } = useTranslation();
  const preferences = usePreferences().data;
  const dateFormat = preferences?.date_format;
  const numberFormat = preferences?.number_format;
  return useMemo(
    () => formatsOf(i18n.language, dateFormat, numberFormat),
    [i18n.language, dateFormat, numberFormat],
  );
}
