"use client";

import { useCallback, useMemo, useState } from "react";

import DependencyGraph from "@/components/DependencyGraph";
import {
  ApiError,
  createProject,
  getProjectDetails,
  scanProject,
  type DebtItem,
  type ProjectDetail,
  type ScanSummary,
  type Severity,
} from "@/lib/api";

const DEFAULT_DIRECTORY =
  "/workspaces/LivingArchitectureAndTechnicalDebtMapper/backend";

const SEVERITY_STYLES: Record<Severity, string> = {
  critical:
    "bg-red-100 text-red-800 ring-red-600/20 dark:bg-red-500/15 dark:text-red-300 dark:ring-red-400/30",
  high: "bg-red-100 text-red-800 ring-red-600/20 dark:bg-red-500/15 dark:text-red-300 dark:ring-red-400/30",
  medium:
    "bg-amber-100 text-amber-900 ring-amber-600/20 dark:bg-amber-500/15 dark:text-amber-300 dark:ring-amber-400/30",
  low: "bg-emerald-100 text-emerald-800 ring-emerald-600/20 dark:bg-emerald-500/15 dark:text-emerald-300 dark:ring-emerald-400/30",
};

const SEVERITY_ORDER: Record<Severity, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize ring-1 ring-inset ${SEVERITY_STYLES[severity]}`}
    >
      {severity}
    </span>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <dt className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        {label}
      </dt>
      <dd className="mt-2 text-3xl font-semibold tabular-nums text-zinc-900 dark:text-zinc-50">
        {value.toLocaleString()}
      </dd>
    </div>
  );
}

export default function Home() {
  const [name, setName] = useState("");
  const [repositoryUrl, setRepositoryUrl] = useState("");
  const [directoryPath, setDirectoryPath] = useState(DEFAULT_DIRECTORY);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<ScanSummary | null>(null);
  const [project, setProject] = useState<ProjectDetail | null>(null);

  const debtItems = useMemo(() => {
    if (!project) return [];
    return [...project.debt_items].sort(
      (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity],
    );
  }, [project]);

  const handleSubmit = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (isSubmitting) return;

      setError(null);
      setSummary(null);
      setProject(null);
      setIsSubmitting(true);

      try {
        const created = await createProject(name.trim(), repositoryUrl.trim());
        const scanResult = await scanProject(created.id, directoryPath.trim());
        setSummary(scanResult);

        // Re-read through the detail endpoint so the table reflects what was
        // actually persisted, not what the scan reported.
        setProject(await getProjectDetails(created.id));
      } catch (cause) {
        const message =
          cause instanceof ApiError
            ? cause.message
            : "Something went wrong while creating or scanning the project.";
        setError(message);
      } finally {
        setIsSubmitting(false);
      }
    },
    [directoryPath, isSubmitting, name, repositoryUrl],
  );

  const inputClasses =
    "w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 shadow-sm outline-none transition placeholder:text-zinc-400 focus:border-zinc-900 focus:ring-2 focus:ring-zinc-900/10 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100 dark:placeholder:text-zinc-500 dark:focus:border-zinc-300 dark:focus:ring-zinc-100/10";

  const labelClasses =
    "mb-1.5 block text-sm font-medium text-zinc-700 dark:text-zinc-300";

  return (
    <div className="flex-1 bg-zinc-50 dark:bg-black">
      <div className="mx-auto w-full max-w-5xl px-6 py-12">
        <header className="mb-10">
          <h1 className="text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
            CodeCompass
          </h1>
          <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
            Map a Python codebase&apos;s import graph and surface technical debt.
          </p>
        </header>

        <section className="rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">
            Add Project
          </h2>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            The directory must be readable by the API process.
          </p>

          <form onSubmit={handleSubmit} className="mt-6 space-y-5">
            <div className="grid gap-5 sm:grid-cols-2">
              <div>
                <label htmlFor="project-name" className={labelClasses}>
                  Project Name
                </label>
                <input
                  id="project-name"
                  name="project-name"
                  type="text"
                  required
                  maxLength={255}
                  placeholder="codecompass-api"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  disabled={isSubmitting}
                  className={inputClasses}
                />
              </div>

              <div>
                <label htmlFor="repository-url" className={labelClasses}>
                  Repository URL
                </label>
                <input
                  id="repository-url"
                  name="repository-url"
                  type="url"
                  required
                  maxLength={2048}
                  placeholder="https://github.com/acme/codecompass"
                  value={repositoryUrl}
                  onChange={(event) => setRepositoryUrl(event.target.value)}
                  disabled={isSubmitting}
                  className={inputClasses}
                />
              </div>
            </div>

            <div>
              <label htmlFor="directory-path" className={labelClasses}>
                Local Directory Path to Scan
              </label>
              <input
                id="directory-path"
                name="directory-path"
                type="text"
                required
                maxLength={4096}
                value={directoryPath}
                onChange={(event) => setDirectoryPath(event.target.value)}
                disabled={isSubmitting}
                className={`${inputClasses} font-mono`}
              />
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="submit"
                disabled={isSubmitting}
                className="inline-flex items-center justify-center rounded-lg bg-zinc-900 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-zinc-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-900 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200 dark:focus-visible:ring-zinc-100 dark:focus-visible:ring-offset-zinc-900"
              >
                {isSubmitting ? "Scanning…" : "Create & Scan"}
              </button>
              {isSubmitting ? (
                <span className="text-sm text-zinc-500 dark:text-zinc-400">
                  Parsing files and writing results…
                </span>
              ) : null}
            </div>
          </form>

          {error ? (
            <div
              role="alert"
              className="mt-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300"
            >
              {error}
            </div>
          ) : null}
        </section>

        {summary && project ? (
          <section className="mt-8 space-y-8">
            <div>
              <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">
                  Scan Summary
                </h2>
                <p className="text-sm text-zinc-600 dark:text-zinc-400">
                  {project.name}
                </p>
              </div>
              <dl className="grid gap-4 sm:grid-cols-3">
                <StatCard label="Files Scanned" value={summary.files_scanned} />
                <StatCard
                  label="Dependencies Found"
                  value={summary.dependencies_found}
                />
                <StatCard
                  label="Debt Items Found"
                  value={summary.debt_items_found}
                />
              </dl>
            </div>

            <div>
              <h2 className="mb-4 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
                Dependency Graph
              </h2>
              <DependencyGraph dependencies={project.dependencies} />
            </div>

            <div>
              <h2 className="mb-4 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
                Technical Debt
              </h2>

              {debtItems.length === 0 ? (
                <div className="rounded-xl border border-dashed border-zinc-300 bg-white px-6 py-10 text-center text-sm text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400">
                  No debt items detected in this scan.
                </div>
              ) : (
                <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-zinc-200 text-left text-sm dark:divide-zinc-800">
                      <thead className="bg-zinc-50 dark:bg-zinc-950/60">
                        <tr>
                          {[
                            "File Path",
                            "Severity",
                            "Category",
                            "Proposed Fix",
                          ].map((heading) => (
                            <th
                              key={heading}
                              scope="col"
                              className="whitespace-nowrap px-4 py-3 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400"
                            >
                              {heading}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                        {debtItems.map((item: DebtItem) => (
                          <tr
                            key={item.id}
                            className="align-top transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
                          >
                            <td className="px-4 py-3 font-mono text-xs text-zinc-800 dark:text-zinc-200">
                              {item.file_path ?? "—"}
                              {item.line_number !== null ? (
                                <span className="ml-1 text-zinc-500 dark:text-zinc-400">
                                  ({item.line_number} lines)
                                </span>
                              ) : null}
                            </td>
                            <td className="px-4 py-3">
                              <SeverityBadge severity={item.severity} />
                            </td>
                            <td className="whitespace-nowrap px-4 py-3 text-zinc-700 dark:text-zinc-300">
                              {item.category}
                            </td>
                            <td className="px-4 py-3 text-zinc-700 dark:text-zinc-300">
                              {item.proposed_fix ?? "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          </section>
        ) : null}
      </div>
    </div>
  );
}
