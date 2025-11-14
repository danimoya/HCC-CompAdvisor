# HCC Compression Advisor - Usage Examples

## Table of Contents
1. [Basic Setup](#basic-setup)
2. [Identifying Candidates](#identifying-candidates)
3. [Generating Recommendations](#generating-recommendations)
4. [Executing Compression](#executing-compression)
5. [Complete Workflow](#complete-workflow)
6. [History and Reporting](#history-and-reporting)
7. [Advanced Usage](#advanced-usage)

---

## Basic Setup

### Environment Variables

```bash
# Required
export DB_USER="compression_admin"
export DB_PASSWORD="your_secure_password"
export DB_CONNECT_STRING="exadata-scan:1521/proddb"

# Optional
export DB_POOL_MIN=2
export DB_POOL_MAX=10
export MIN_TABLE_SIZE_MB=100
export MIN_COMPRESSION_RATIO=2.0
export LOG_LEVEL=info
export LOG_FILE=logs/compression-advisor.log
```

### Configuration File (config.json)

```json
{
  "database": {
    "user": "compression_admin",
    "password": "secure_password",
    "connectString": "exadata-scan:1521/proddb",
    "poolMin": 2,
    "poolMax": 10
  },
  "compression": {
    "minTableSizeMB": 100,
    "minCompressionRatio": 2.0,
    "maxConcurrentOps": 3,
    "defaultCompressionType": "QUERY LOW",
    "excludedSchemas": ["SYS", "SYSTEM", "OUTLN"],
    "excludedTablePatterns": ["TMP_", "TEMP_", "BACKUP_"]
  },
  "logging": {
    "level": "info",
    "file": "logs/compression-advisor.log",
    "enableConsole": true
  },
  "history": {
    "retentionDays": 90,
    "tableName": "COMPRESSION_HISTORY",
    "schemaName": "ADMIN"
  }
}
```

### Basic Initialization

```javascript
const HCCCompressionAdvisor = require('./src/index');

async function main() {
  const advisor = new HCCCompressionAdvisor();

  try {
    // Initialize with environment variables
    await advisor.initialize();

    // Or initialize with config file
    // await advisor.initialize('config/production.json');

    console.log('Advisor initialized successfully');

    // Your code here

  } finally {
    await advisor.shutdown();
  }
}

main().catch(console.error);
```

---

## Identifying Candidates

### Find All Candidates

```javascript
const advisor = new HCCCompressionAdvisor();
await advisor.initialize();

try {
  // Find all compression candidates
  const candidates = await advisor.identifyCandidates();

  console.log(`Found ${candidates.length} compression candidates`);

  // Display top 10
  candidates.slice(0, 10).forEach(c => {
    console.log(`${c.schemaName}.${c.tableName}`);
    console.log(`  Size: ${c.sizeMB.toFixed(2)} MB`);
    console.log(`  Score: ${c.score}`);
    console.log(`  Estimated Ratio: ${c.estimatedCompressionRatio}x`);
    console.log('---');
  });

} finally {
  await advisor.shutdown();
}
```

### Filter by Schema

```javascript
// Analyze specific schemas
const candidates = await advisor.identifyCandidates({
  schemas: ['SALES', 'FINANCE', 'OPERATIONS']
});

console.log(`Found ${candidates.length} candidates in specified schemas`);
```

### Filter by Size

```javascript
// Only tables larger than 1GB
const candidates = await advisor.identifyCandidates({
  minSizeMB: 1024,
  limit: 50
});

console.log(`Found ${candidates.length} candidates over 1GB`);
```

### Read-Heavy Workloads Only

```javascript
// Find read-heavy tables (good HCC candidates)
const candidates = await advisor.identifyCandidates({
  readHeavy: true,
  minCompressionRatio: 3.0
});

console.log(`Found ${candidates.length} read-heavy candidates`);
```

### Recent Statistics Only

```javascript
// Only tables with stats gathered in last 30 days
const candidates = await advisor.identifyCandidates({
  requireRecentStats: true,
  minSizeMB: 500
});
```

---

## Generating Recommendations

### Single Table Analysis

```javascript
const advisor = new HCCCompressionAdvisor();
await advisor.initialize();

try {
  // Analyze specific table
  const analysis = await advisor.analyzeTable('SALES', 'ORDERS');

  console.log('Table Analysis:');
  console.log(`Size: ${analysis.table.sizeMB} MB`);
  console.log(`Rows: ${analysis.table.numRows}`);
  console.log(`Compression: ${analysis.table.compression}`);
  console.log(`Partitioned: ${analysis.table.partitioned}`);

  console.log(`\nColumns: ${analysis.columns.length}`);
  console.log(`Indexes: ${analysis.indexes.length}`);
  console.log(`Partitions: ${analysis.partitions.length}`);

  // Generate recommendation
  const recommendation = await advisor.generateRecommendation(analysis);

  console.log('\nRecommendation:');
  console.log(`Type: ${recommendation.recommendedCompression.name}`);
  console.log(`Expected Ratio: ${recommendation.expectedSavings.expectedRatio}x`);
  console.log(`Expected Savings: ${recommendation.expectedSavings.savedFormatted}`);
  console.log(`Priority: ${recommendation.priority}`);
  console.log(`Risk Level: ${recommendation.riskAssessment.riskLevel}`);

  // Display implementation steps
  console.log('\nImplementation Steps:');
  recommendation.implementationStrategy.steps.forEach(step => {
    console.log(`${step.order}. ${step.action}`);
    console.log(`   SQL: ${step.sql.substring(0, 80)}...`);
  });

} finally {
  await advisor.shutdown();
}
```

### Batch Recommendations

```javascript
// Get candidates and generate batch recommendations
const candidates = await advisor.identifyCandidates({
  minSizeMB: 500,
  limit: 100
});

const recommendations = await advisor.generateBatchRecommendations(candidates);

// Filter by priority
const highPriority = recommendations.filter(r => r.priority === 'HIGH');

console.log(`High Priority Recommendations: ${highPriority.length}`);

highPriority.forEach(rec => {
  console.log(`${rec.table.schema}.${rec.table.name}`);
  console.log(`  Current: ${rec.table.currentSize}`);
  console.log(`  Savings: ${rec.expectedSavings.savedFormatted} (${rec.expectedSavings.percentageSaved}%)`);
  console.log(`  Type: ${rec.recommendedCompression.name}`);
});
```

---

## Executing Compression

### Dry Run (Generate DDL Only)

```javascript
const advisor = new HCCCompressionAdvisor();
await advisor.initialize();

try {
  // Analyze and recommend
  const analysis = await advisor.analyzeTable('SALES', 'ORDERS');
  const recommendation = await advisor.generateRecommendation(analysis);

  // Dry run - generate DDL without executing
  const result = await advisor.executeCompression(recommendation, {
    dryRun: true
  });

  console.log('Generated DDL:');
  console.log('\n--- Pre-Compression ---');
  result.ddl.preCompression.forEach(step => {
    console.log(`-- ${step.description}`);
    console.log(step.sql);
    console.log('');
  });

  console.log('\n--- Compression ---');
  result.ddl.compression.forEach(step => {
    console.log(`-- ${step.description}`);
    console.log(step.sql);
    if (step.warning) console.log(`-- WARNING: ${step.warning}`);
    console.log('');
  });

  console.log('\n--- Post-Compression ---');
  result.ddl.postCompression.forEach(step => {
    console.log(`-- ${step.description}`);
    console.log(step.sql);
    console.log('');
  });

} finally {
  await advisor.shutdown();
}
```

### Execute Compression

```javascript
// Real execution
const result = await advisor.executeCompression(recommendation, {
  dryRun: false,
  parallel: 4  // Use parallel 4
});

if (result.status === 'COMPLETED') {
  console.log('Compression completed successfully!');
  console.log(`Before: ${result.beforeStats.sizeMB} MB`);
  console.log(`After: ${result.afterStats.sizeMB} MB`);
  console.log(`Actual Ratio: ${result.actualSavings.compressionRatio}x`);
  console.log(`Space Saved: ${result.actualSavings.savedBytes / (1024*1024)} MB`);
  console.log(`Execution Time: ${result.executionTime}`);
} else {
  console.error(`Compression failed: ${result.status}`);
}
```

### Online Partition Compression

```javascript
// For partitioned tables, use online compression
const result = await advisor.executeCompression(recommendation, {
  dryRun: false,
  online: true,    // Online compression (less downtime)
  parallel: 8      // Higher parallelism
});

console.log(`Compressed ${result.steps.length} partitions`);
```

---

## Complete Workflow

### Automated Workflow

```javascript
const advisor = new HCCCompressionAdvisor();
await advisor.initialize();

try {
  // Complete workflow: identify → recommend → execute
  const results = await advisor.runWorkflow({
    // Identification options
    schemas: ['SALES', 'MARKETING'],
    minSizeMB: 1000,
    readHeavy: true,

    // Execution options
    execute: true,        // Actually execute
    dryRun: false,        // Not a dry run
    online: true,         // Use online compression where possible
    parallel: 4,          // Parallel degree

    includeLowPriority: false  // Skip low priority tables
  });

  console.log('Workflow Summary:');
  console.log(`Candidates Found: ${results.summary.candidatesFound}`);
  console.log(`Recommendations: ${results.summary.recommendationsGenerated}`);
  console.log(`Executions Attempted: ${results.summary.executionsAttempted}`);
  console.log(`Executions Succeeded: ${results.summary.executionsSucceeded}`);
  console.log(`Executions Failed: ${results.summary.executionsFailed}`);
  console.log(`Total Expected Savings: ${results.summary.totalExpectedSavings / (1024*1024*1024)} GB`);
  console.log(`Total Actual Savings: ${results.summary.totalActualSavings / (1024*1024*1024)} GB`);

  // Review failed executions
  const failed = results.executions.filter(e => e.status === 'FAILED');
  if (failed.length > 0) {
    console.log('\nFailed Executions:');
    failed.forEach(f => {
      console.log(`${f.table.schema}.${f.table.name}: ${f.error}`);
    });
  }

} finally {
  await advisor.shutdown();
}
```

### Dry Run Workflow

```javascript
// Generate recommendations and DDL without executing
const results = await advisor.runWorkflow({
  minSizeMB: 500,
  dryRun: true,  // Only generate DDL
  limit: 20
});

console.log(`Generated DDL for ${results.executions.length} tables`);

// Export DDL to file
const fs = require('fs').promises;
const ddlScript = results.executions
  .map(exec => exec.ddl.compression.map(s => s.sql).join(';\n'))
  .join('\n\n');

await fs.writeFile('compression_ddl.sql', ddlScript);
console.log('DDL exported to compression_ddl.sql');
```

---

## History and Reporting

### Table History

```javascript
// Get compression history for a specific table
const history = await advisor.getTableHistory('SALES', 'ORDERS');

console.log(`Found ${history.length} historical records`);

history.forEach(record => {
  console.log(`${record.recordType} - ${record.operationTime}`);
  console.log(`  Status: ${record.status}`);

  if (record.recordType === 'EXECUTION') {
    console.log(`  Before: ${record.beforeSizeMB} MB`);
    console.log(`  After: ${record.afterSizeMB} MB`);
    console.log(`  Ratio: ${record.actualRatio}x`);
    console.log(`  Saved: ${record.actualSavingsMB} MB`);
  } else {
    console.log(`  Recommended: ${record.recommendedCompression}`);
    console.log(`  Expected: ${record.expectedSavingsMB} MB`);
  }
  console.log('---');
});
```

### Statistics Summary

```javascript
// Get overall compression statistics
const stats = await advisor.getStatistics({
  days: 30  // Last 30 days
});

console.log('Compression Statistics (Last 30 Days):');
console.log(`Total Operations: ${stats.totalOperations}`);
console.log(`Recommendations: ${stats.totalRecommendations}`);
console.log(`Executions: ${stats.totalExecutions}`);
console.log(`Success Rate: ${stats.successRate}%`);
console.log(`Total Space Saved: ${stats.totalSpaceSavedMB.toFixed(2)} MB`);
console.log(`Average Compression Ratio: ${stats.avgCompressionRatio.toFixed(2)}x`);
console.log(`Max Compression Ratio: ${stats.maxCompressionRatio.toFixed(2)}x`);
console.log(`Min Compression Ratio: ${stats.minCompressionRatio.toFixed(2)}x`);
```

### Pool Statistics

```javascript
// Monitor connection pool
const poolStats = advisor.getPoolStats();

console.log('Connection Pool Statistics:');
console.log(`Connections In Use: ${poolStats.connectionsInUse}`);
console.log(`Connections Open: ${poolStats.connectionsOpen}`);
console.log(`Pool Min: ${poolStats.poolMin}`);
console.log(`Pool Max: ${poolStats.poolMax}`);
```

---

## Advanced Usage

### Custom Scoring

```javascript
const { CandidateIdentifier } = require('./src/index');

class CustomCandidateIdentifier extends CandidateIdentifier {
  // Override scoring to prioritize specific schemas
  _scoreCandidates(candidates) {
    const scored = super._scoreCandidates(candidates);

    return scored.map(candidate => {
      // Bonus for critical schemas
      if (['SALES', 'FINANCE'].includes(candidate.schemaName)) {
        candidate.score *= 1.5;
      }
      return candidate;
    });
  }
}

// Use custom identifier
const advisor = new HCCCompressionAdvisor();
advisor.candidateIdentifier = new CustomCandidateIdentifier();
```

### Monitoring Execution Progress

```javascript
const { CompressionExecutor } = require('./src/index');

const executor = new CompressionExecutor();

// Start execution
const executionPromise = executor.executeCompression(recommendation);

// Monitor progress
const interval = setInterval(() => {
  const executions = executor.listActiveExecutions();

  executions.forEach(exec => {
    console.log(`${exec.table}: ${exec.status} (${exec.elapsedTime})`);
  });
}, 5000);  // Check every 5 seconds

// Wait for completion
const result = await executionPromise;
clearInterval(interval);
```

### Batch Processing with Concurrency Control

```javascript
const { chunkArray } = require('./src/utils');

// Process in batches of 3
const maxConcurrent = 3;
const candidateChunks = chunkArray(recommendations, maxConcurrent);

for (const chunk of candidateChunks) {
  console.log(`Processing batch of ${chunk.length} tables...`);

  const promises = chunk.map(rec =>
    advisor.executeCompression(rec, { dryRun: false })
  );

  const results = await Promise.allSettled(promises);

  results.forEach((result, idx) => {
    if (result.status === 'fulfilled') {
      console.log(`✓ ${chunk[idx].table.name}: Success`);
    } else {
      console.log(`✗ ${chunk[idx].table.name}: ${result.reason}`);
    }
  });

  // Wait between batches
  await new Promise(resolve => setTimeout(resolve, 60000));  // 1 minute
}
```

### Error Recovery

```javascript
try {
  const result = await advisor.executeCompression(recommendation);
} catch (error) {
  if (error.code === 'EXECUTION_FAILED') {
    console.error('Compression failed:', error.message);
    console.error('Execution ID:', error.details.executionId);

    // Check if rollback was successful
    const status = advisor.compressionExecutor.getExecutionStatus(
      error.details.executionId
    );

    if (status?.status === 'ROLLED_BACK') {
      console.log('Table successfully rolled back to original state');
    } else {
      console.error('Manual intervention required');
    }
  }
}
```

---

## Production Best Practices

### 1. Pilot Testing

```javascript
// Test on small table first
const pilotTable = await advisor.analyzeTable('TEST_SCHEMA', 'SMALL_TABLE');
const pilotRec = await advisor.generateRecommendation(pilotTable);

const pilotResult = await advisor.executeCompression(pilotRec, {
  dryRun: false
});

if (pilotResult.actualSavings.compressionRatio >= 2.0) {
  console.log('Pilot successful, proceeding with production tables');
  // Continue with production
} else {
  console.log('Pilot showed poor compression, aborting');
}
```

### 2. Scheduled Execution

```javascript
// Run during maintenance window
const hour = new Date().getHours();

if (hour >= 2 && hour <= 5) {  // 2 AM - 5 AM
  console.log('Running compression during maintenance window');
  await advisor.runWorkflow({
    execute: true,
    online: false,  // Can use offline compression
    parallel: 8
  });
} else {
  console.log('Outside maintenance window, dry run only');
  await advisor.runWorkflow({
    dryRun: true
  });
}
```

### 3. Notification Integration

```javascript
async function compressWithNotifications(recommendation) {
  const startTime = Date.now();

  try {
    // Send start notification
    await sendNotification({
      subject: 'Compression Started',
      table: `${recommendation.table.schema}.${recommendation.table.name}`,
      timestamp: new Date().toISOString()
    });

    const result = await advisor.executeCompression(recommendation);

    // Send success notification
    await sendNotification({
      subject: 'Compression Completed',
      table: `${recommendation.table.schema}.${recommendation.table.name}`,
      duration: Date.now() - startTime,
      savings: result.actualSavings.savedFormatted,
      ratio: result.actualSavings.compressionRatio
    });

  } catch (error) {
    // Send error notification
    await sendNotification({
      subject: 'Compression Failed',
      table: `${recommendation.table.schema}.${recommendation.table.name}`,
      error: error.message,
      timestamp: new Date().toISOString()
    });

    throw error;
  }
}
```

This comprehensive set of examples covers all major use cases for the HCC Compression Advisor system.
