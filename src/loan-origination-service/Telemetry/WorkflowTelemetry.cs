using System.Diagnostics;

namespace LoanOrigination.Telemetry;

public class WorkflowTelemetry
{
    private static readonly ActivitySource ActivitySource = new("LoanOrigination.Workflow");

    public static Activity? StartWorkflowActivity(string workflowName, string applicationNo, string runId)
    {
        var activity = ActivitySource.StartActivity($"Workflow.{workflowName}", ActivityKind.Internal);
        
        activity?.SetTag("workflow.name", workflowName);
        activity?.SetTag("workflow.application_no", applicationNo);
        activity?.SetTag("workflow.run_id", runId);
        
        return activity;
    }

    public static Activity? StartStepActivity(string stepId, string applicationNo, string runId, string? stepName = null)
    {
        var activity = ActivitySource.StartActivity($"Workflow.Step.{stepId}", ActivityKind.Internal);
        
        activity?.SetTag("workflow.step_id", stepId);
        activity?.SetTag("workflow.application_no", applicationNo);
        activity?.SetTag("workflow.run_id", runId);
        
        if (!string.IsNullOrEmpty(stepName))
        {
            activity?.SetTag("workflow.step_name", stepName);
        }
        
        return activity;
    }

    public static Activity? StartStepSpan(string stepId, string applicationNo, string runId, string? stepName = null)
    {
        // Legacy alias for backward compatibility
        return StartStepActivity(stepId, applicationNo, runId, stepName);
    }

    public static ActivitySource GetActivitySource() => ActivitySource;
}
