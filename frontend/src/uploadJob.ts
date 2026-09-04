import { getUploadJob } from "./api";
import type { JobStatusResponse } from "./types";

const POLL_INTERVAL_MS = 800;

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// /upload just enqueues a background ingest job (the actual PDF parsing +
// embedding can take seconds to minutes) and returns a job_id immediately --
// poll /upload/jobs/{job_id} until it leaves the queued/processing states.
export async function pollJobUntilDone(jobId: string): Promise<JobStatusResponse> {
  for (;;) {
    const job = await getUploadJob(jobId);
    if (job.status === "done" || job.status === "error") return job;
    await sleep(POLL_INTERVAL_MS);
  }
}
