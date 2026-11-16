# Editable architecture diagrams

The current architecture drawings use native draw.io sources:

- `general_architecture.drawio`: grouped task definition (a), alternative execution
  environments (b), and retained evidence (c). Only enclosing panels are connected
  across these stages. The containers hold their children, so moving a panel moves
  its contents; individual cards do not imply one-to-one mappings.
- `local_execution.drawio`: separate workbench and portable-runner paths. This is
  supporting artwork, not a substitute for the paper's actual viewer screenshot.
- `aws_infrastructure.drawio`: the two-page AWS reference architecture below.

Edit these sources in draw.io, then export with
`python artifacts/generate_architecture.py --drawio /path/to/drawio` from the
repository root. Source generators reset manual edits; the export command does
not. All current diagrams were exported offline with draw.io Desktop 32.6.10.
The measured-result plots deliberately remain Matplotlib figures generated from
data; they are not redrawn as diagram shapes. Historical TikZ drawings are inactive.

## AWS reference architecture

Open `aws_infrastructure.drawio` in draw.io Desktop, or choose **File → Open from → Device** in diagrams.net. The file contains native, editable shapes and AWS service icons, not a flattened image. There are two tabs:

1. **Execution architecture:** researcher/API submission, ALB and Fargate, SQS, dispatcher, Step Functions, CPU preparation, GPU Spot workers, On-Demand fallback, and shared services.
2. **Assets, events and operations:** S3 artifact flow, finalization, DynamoDB, Batch events and reconciliation, ECR image distribution, and CloudWatch/SNS alerts.

The diagram describes the repository's AWS reference implementation, not a deployed or experimentally validated cloud service. Dashed FSx storage is planned, not provisioned. Notes identify incomplete MSA integration, recovery/publication semantics, failure classification, and production ingress security. AWS priority projection is not the portable UAF-SJF policy evaluated in the GPU experiments.

Edit labels directly; service cards are groups that can be moved together or ungrouped. Use **File → Export as → SVG** or **PDF** for a publication figure. For two-column articles, consider using each page as a separate full-width figure rather than shrinking both into one column.

Regenerate from the repository root with:

```sh
python3 artifacts/generate_aws_drawio.py
```

Regeneration overwrites the diagram, so preserve manual draw.io edits separately or update the generator first. The generator checks unique cell identifiers and resolved parent/connector references. Both pages were exported with draw.io Desktop 32.6.10 in a network-disabled container and visually checked. No architecture XML was uploaded.

The publication exports are `aws_execution.pdf` and `aws_operations.pdf`. Regenerate after editing the diagram with:

```sh
drawio --export --format pdf --crop --page-index 1 --output artifacts/diagrams/aws_execution.pdf artifacts/diagrams/aws_infrastructure.drawio
drawio --export --format pdf --crop --page-index 2 --output artifacts/diagrams/aws_operations.pdf artifacts/diagrams/aws_infrastructure.drawio
```

In the separate manuscript repository, the execution export replaces the AWS figure in the main article; the operations export is Supplementary Figure S1. Pre-rendered figures allow Overleaf compilation without draw.io. The paper and both repositories' editable sources must be synchronized after future edits.

Icons use the native `mxgraph.aws4` library included in draw.io. No account IDs, credentials, or deployment-specific endpoints are embedded.
