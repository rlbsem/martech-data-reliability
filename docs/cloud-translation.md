# Unexecuted AWS and Redshift translation

**Only the local Python/DuckDB implementation was executed.** This is a proposed mapping, not provisioned infrastructure, a vendor integration, a performance result or professional production experience.

| Executed local responsibility | Proposed managed counterpart | Engineering work still required |
|---|---|---|
| Hash-named local landing files | S3 objects keyed by content hash | Conditional writes, explicit checksum verification, retention/IAM/encryption and upload recovery |
| Serialized command sequence | Scheduled container job, with orchestration if needed | Single-writer fencing, retries, alert routing, secrets and run cancellation |
| DuckDB admitted versions and receipts | Redshift staging and revision tables | Batch loading, key enforcement, duplicate detection and transaction testing |
| Pinned run inputs and SQL candidate | Run-scoped staging tables plus warehouse SQL | Distribution/sort strategy, workload sizing, isolation and retention |
| Independent gate then publication pointer | Checked candidate plus warehouse publication record/view | Prove atomic exposure and stale-run fencing under real concurrent readers/writers |

S3 conditional writes can prevent overwriting an existing object key. They do not make the filesystem/database protocol automatically correct in a cloud deployment; upload/receipt recovery must be re-tested. Store the pipeline's content checksum explicitly rather than assuming an object ETag is that checksum. [AWS conditional-write documentation](https://docs.aws.amazon.com/us_en/AmazonS3/latest/userguide/conditional-writes.html).

Redshift supports loading S3 data using `COPY`, including an explicit file manifest. The translation would batch normalized rows instead of retaining this laboratory's row-wise inserts. [Redshift S3 loading](https://docs.aws.amazon.com/redshift/latest/dg/t_loading-tables-from-s3.html).

Crucially, Redshift does **not** enforce primary-key, unique or foreign-key constraints. Copying the local DDL would lose a correctness boundary. The loader would need enforced serialization/fencing, explicit uniqueness checks and conflict detection before publication. [Redshift constraint semantics](https://docs.aws.amazon.com/en_en/redshift/latest/dg/t_Defining_constraints.html).

dbt could organize a larger transformation DAG and warehouse tests; it would not replace source receipts or solve the S3-to-warehouse commit gap. Scale testing, credentials, privacy retention, disaster recovery, production monitoring and vendor-specific extraction semantics remain unimplemented. One carefully bounded mapping is more informative here than claiming portability to every cloud.
