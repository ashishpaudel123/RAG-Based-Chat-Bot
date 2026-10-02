"use client";

import { useEffect, useState } from "react";
import { api, type Profile } from "./api";

const FALLBACK: Profile = {
  id: "",
  assistant_name: "Assistant",
  tagline: "Answers come from the approved knowledge base, with sources shown so you can check them.",
  suggestions: [],
  answer_format: "simple",
};

let cached: Promise<Profile> | null = null;

/** Assistant name, tagline and suggested questions from the backend's domain profile. */
export function useProfile(): Profile {
  const [profile, setProfile] = useState<Profile>(FALLBACK);
  useEffect(() => {
    cached ??= api.profile().catch(() => {
      cached = null;
      return FALLBACK;
    });
    let alive = true;
    cached.then((p) => {
      if (!alive) return;
      setProfile(p);
      if (p.assistant_name) document.title = p.assistant_name;
    });
    return () => {
      alive = false;
    };
  }, []);
  return profile;
}
