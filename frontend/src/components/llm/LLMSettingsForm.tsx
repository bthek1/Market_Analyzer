import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useLLMSettings, useUpdateLLMSettings } from "@/hooks/useLLMSettings";
import { llmSettingsSchema, type LLMSettingsFormValues } from "@/schemas/llm";

export function LLMSettingsForm({ onSaved }: { onSaved?: () => void }) {
  const { data, isLoading, isError } = useLLMSettings();
  const { mutate, isPending, isSuccess, error } = useUpdateLLMSettings();

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isDirty },
  } = useForm<LLMSettingsFormValues>({ resolver: zodResolver(llmSettingsSchema) });

  // Hydrate the form once the current config loads.
  useEffect(() => {
    if (data) {
      const { updated_at: _updated, ...values } = data;
      reset(values);
    }
  }, [data, reset]);

  return (
    <>
      <h2 className="text-lg font-semibold tracking-tight mb-1">LLM Settings</h2>
      <p className="text-sm text-muted-foreground mb-6">
        Runtime Ollama configuration. Changes take effect immediately for new requests.
      </p>

      {isLoading && <p className="text-sm text-muted-foreground">Loading...</p>}
      {isError && <p className="text-sm text-destructive">Failed to load settings.</p>}

      {data && (
        <form
          onSubmit={handleSubmit((values) =>
            mutate(values, { onSuccess: () => onSaved?.() }),
          )}
          className="space-y-6"
        >
          <Card>
            <CardHeader>
              <CardTitle>Connection</CardTitle>
              <CardDescription>Ollama server endpoint and request limits.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <Field label="Base URL" id="base_url" error={errors.base_url?.message}>
                <Input id="base_url" {...register("base_url")} />
              </Field>
              <Field label="Timeout (s)" id="timeout" error={errors.timeout?.message}>
                <Input id="timeout" type="number" {...register("timeout")} />
              </Field>
              <Field
                label="Num parallel"
                id="num_parallel"
                error={errors.num_parallel?.message}
              >
                <Input id="num_parallel" type="number" {...register("num_parallel")} />
              </Field>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Models</CardTitle>
              <CardDescription>Per-role Ollama model names.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <Field label="Main model" id="main_model" error={errors.main_model?.message}>
                <Input id="main_model" {...register("main_model")} />
              </Field>
              <Field
                label="Classifier model"
                id="classifier_model"
                error={errors.classifier_model?.message}
              >
                <Input id="classifier_model" {...register("classifier_model")} />
              </Field>
              <Field label="Embed model" id="embed_model" error={errors.embed_model?.message}>
                <Input id="embed_model" {...register("embed_model")} />
              </Field>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Routing</CardTitle>
              <CardDescription>How incoming queries are routed to a workflow.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <Field label="Route mode" id="route_mode" error={errors.route_mode?.message}>
                <select
                  id="route_mode"
                  {...register("route_mode")}
                  className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  <option value="llm">llm (classifier model)</option>
                  <option value="semantic">semantic (embeddings)</option>
                </select>
              </Field>
              <Field
                label="Route threshold"
                id="route_threshold"
                error={errors.route_threshold?.message}
              >
                <Input
                  id="route_threshold"
                  type="number"
                  step="0.01"
                  {...register("route_threshold")}
                />
              </Field>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Agents</CardTitle>
              <CardDescription>Iteration caps and quality thresholds.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <Field
                label="ReAct max steps"
                id="react_max_steps"
                error={errors.react_max_steps?.message}
              >
                <Input id="react_max_steps" type="number" {...register("react_max_steps")} />
              </Field>
              <Field
                label="Eval max iterations"
                id="eval_max_iterations"
                error={errors.eval_max_iterations?.message}
              >
                <Input
                  id="eval_max_iterations"
                  type="number"
                  {...register("eval_max_iterations")}
                />
              </Field>
              <Field
                label="Eval threshold (0-10)"
                id="eval_threshold"
                error={errors.eval_threshold?.message}
              >
                <Input id="eval_threshold" type="number" {...register("eval_threshold")} />
              </Field>
              <Field
                label="Plan max steps"
                id="plan_max_steps"
                error={errors.plan_max_steps?.message}
              >
                <Input id="plan_max_steps" type="number" {...register("plan_max_steps")} />
              </Field>
              <Field
                label="Plan max replans"
                id="plan_max_replans"
                error={errors.plan_max_replans?.message}
              >
                <Input id="plan_max_replans" type="number" {...register("plan_max_replans")} />
              </Field>
              <Field
                label="Orchestrator max workers (2-8)"
                id="orch_max_workers"
                error={errors.orch_max_workers?.message}
              >
                <Input id="orch_max_workers" type="number" {...register("orch_max_workers")} />
              </Field>
              <Field
                label="Multi-agent researcher tool budget (1-10)"
                id="multiagent_max_tools"
                error={errors.multiagent_max_tools?.message}
              >
                <Input
                  id="multiagent_max_tools"
                  type="number"
                  {...register("multiagent_max_tools")}
                />
              </Field>
              <Field
                label="DAG max nodes (2-12)"
                id="dag_max_nodes"
                error={errors.dag_max_nodes?.message}
              >
                <Input id="dag_max_nodes" type="number" {...register("dag_max_nodes")} />
              </Field>
              <Field
                label="Autonomous max cycles (1-20)"
                id="auto_max_cycles"
                error={errors.auto_max_cycles?.message}
              >
                <Input id="auto_max_cycles" type="number" {...register("auto_max_cycles")} />
              </Field>
              <Field
                label="Autonomous max sub-agents (0-6)"
                id="auto_max_subagents"
                error={errors.auto_max_subagents?.message}
              >
                <Input
                  id="auto_max_subagents"
                  type="number"
                  {...register("auto_max_subagents")}
                />
              </Field>
              <Field
                label="Autonomous sub-agent step budget (1-6)"
                id="auto_subagent_steps"
                error={errors.auto_subagent_steps?.message}
              >
                <Input
                  id="auto_subagent_steps"
                  type="number"
                  {...register("auto_subagent_steps")}
                />
              </Field>
              <Field
                label="Autonomous no-progress limit (1-10)"
                id="auto_no_progress"
                error={errors.auto_no_progress?.message}
              >
                <Input id="auto_no_progress" type="number" {...register("auto_no_progress")} />
              </Field>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Browser agent</CardTitle>
              <CardDescription>
                Powers the Browse page. The only agent that reaches the public internet, so
                it ships disabled and every field below is a hard bound.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <Field
                label="Enabled"
                id="browser_enabled"
                error={errors.browser_enabled?.message}
              >
                <input
                  id="browser_enabled"
                  type="checkbox"
                  className="size-4 align-middle"
                  {...register("browser_enabled")}
                />
              </Field>
              <Field
                label="Provider"
                id="browser_provider"
                error={errors.browser_provider?.message}
              >
                <select
                  id="browser_provider"
                  className="h-9 w-full rounded-md border bg-background px-2 text-sm"
                  {...register("browser_provider")}
                >
                  <option value="ollama">Ollama (local, free)</option>
                  <option value="anthropic">Anthropic (needs API key)</option>
                </select>
              </Field>
              <Field
                label="Model"
                id="browser_model"
                error={errors.browser_model?.message}
              >
                <Input id="browser_model" {...register("browser_model")} />
              </Field>
              <Field
                label="Max steps (1-40)"
                id="browser_max_steps"
                error={errors.browser_max_steps?.message}
              >
                <Input
                  id="browser_max_steps"
                  type="number"
                  {...register("browser_max_steps")}
                />
              </Field>
              <Field
                label="Timeout (30-1800 s)"
                id="browser_timeout_s"
                error={errors.browser_timeout_s?.message}
              >
                <Input
                  id="browser_timeout_s"
                  type="number"
                  {...register("browser_timeout_s")}
                />
              </Field>
              <Field
                label="Headless"
                id="browser_headless"
                error={errors.browser_headless?.message}
              >
                <input
                  id="browser_headless"
                  type="checkbox"
                  className="size-4 align-middle"
                  {...register("browser_headless")}
                />
              </Field>
              <div className="sm:col-span-2">
                <Field
                  label="Allowed domains (one per line; blank means any host)"
                  id="browser_allowed_domains"
                  error={errors.browser_allowed_domains?.message}
                >
                  <textarea
                    id="browser_allowed_domains"
                    rows={4}
                    className="w-full rounded-md border bg-background px-3 py-2 font-mono text-xs"
                    {...register("browser_allowed_domains")}
                  />
                </Field>
              </div>
            </CardContent>
          </Card>

          <div className="flex items-center gap-3">
            <Button type="submit" disabled={isPending || !isDirty}>
              {isPending ? "Saving..." : "Save changes"}
            </Button>
            {isSuccess && !isDirty && (
              <span className="text-sm text-muted-foreground">Saved.</span>
            )}
            {error && <span className="text-sm text-destructive">Failed to save.</span>}
          </div>
        </form>
      )}
    </>
  );
}

function Field({
  label,
  id,
  error,
  children,
}: {
  label: string;
  id: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
