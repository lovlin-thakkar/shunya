"use client";

import { useEffect, useState } from "react";

import { fetchRecordingBlobUrl } from "@/lib/api";

/**
 * Plays a run's call recording. The audio is fetched through the authenticated,
 * tenant-scoped API (GET /api/v1/test-runs/<id>/recording/) into a blob URL,
 * because a raw <audio src> can't carry the Api-Key header.
 */
export function RecordingPlayer({ runId }: { runId: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;

    setUrl(null);
    setFailed(false);
    fetchRecordingBlobUrl(runId)
      .then((u) => {
        if (active) {
          objectUrl = u;
          setUrl(u);
        } else {
          URL.revokeObjectURL(u);
        }
      })
      .catch(() => {
        if (active) setFailed(true);
      });

    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [runId]);

  if (failed) {
    return (
      <p className="text-xs" style={{ color: "var(--ink-3)" }}>
        Recording unavailable.
      </p>
    );
  }

  if (!url) {
    return (
      <p className="text-xs" style={{ color: "var(--ink-3)" }}>
        Loading recording…
      </p>
    );
  }

  return (
    <>
      <audio
        controls
        className="w-full h-8"
        style={{ accentColor: "var(--blue)" }}
        src={url}
      />
      <p className="text-xs mt-2" style={{ color: "var(--ink-3)" }}>
        <a
          href={url}
          download={`${runId}.wav`}
          className="underline underline-offset-2"
          style={{ color: "var(--blue)" }}
        >
          {runId}.wav
        </a>
      </p>
    </>
  );
}
