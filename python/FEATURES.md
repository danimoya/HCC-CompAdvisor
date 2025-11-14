# HCC Compression Advisor - Feature Documentation

Comprehensive feature list and usage guide for the Streamlit Dashboard.

## 🎯 Core Features

### 1. Authentication & Security

#### Password-Based Authentication
- **Login System:** Secure password authentication
- **Session Management:** Automatic session timeout
- **Login Protection:** Maximum login attempt limits
- **Session Tracking:** Last activity monitoring

**Configuration:**
```env
DASHBOARD_PASSWORD=YourSecurePassword
SESSION_TIMEOUT_MINUTES=30
MAX_LOGIN_ATTEMPTS=3
```

**Usage:**
- Access dashboard URL
- Enter password
- Session auto-expires after inactivity
- Logout button in sidebar

#### SSL/HTTPS Support
- **Self-Signed Certificates:** Development use
- **CA Certificates:** Production ready
- **Encrypted Traffic:** All data encrypted
- **Certificate Validation:** Browser security

**Setup:**
```bash
cd ssl
./generate_cert.sh
```

**Start with SSL:**
```bash
./start.sh  # HTTPS by default
./start.sh http  # HTTP for development
```

### 2. Dashboard Overview

#### Main Dashboard
- **Key Metrics:** Total tables, sizes, savings
- **Visual Charts:** Savings by strategy
- **Recent Activity:** Latest executions
- **Quick Actions:** One-click navigation
- **Connection Status:** Real-time health checks

**Metrics Displayed:**
- Total tables analyzed
- Total current size (GB)
- Compressed size (GB)
- Average savings percentage

**Charts:**
- Savings by strategy (bar chart)
- Recent executions (activity feed)

### 3. Compression Analysis

#### Start Analysis
- **Configurable Parameters:** Minimum table size
- **Progress Monitoring:** Real-time status
- **Result Visualization:** Size comparison
- **Candidate Preview:** Top recommendations

**Features:**
- Set minimum table size threshold
- Analyze all schemas or specific schemas
- View analysis progress
- Export results

**Analysis Results:**
- Analysis ID and timestamp
- Tables analyzed count
- Candidates found
- Total current vs compressed size
- Potential savings in GB and %

#### Analysis Visualization
- **Size Comparison Chart:** Before/after visualization
- **Savings Distribution:** Histogram
- **Strategy Breakdown:** Pie chart
- **Top Candidates Table:** Detailed list

### 4. Compression Recommendations

#### View Recommendations
- **Smart Filtering:** By strategy, size, savings
- **Sorting Options:** Multiple criteria
- **Detailed Metrics:** Per-table statistics
- **Visual Analytics:** Charts and graphs

**Filter Options:**
- Compression strategy (QUERY LOW/HIGH, ARCHIVE LOW/HIGH)
- Minimum savings percentage
- Minimum table size (MB)
- Maximum results limit

**Display Columns:**
- Table owner and name
- Current size (MB)
- Recommended strategy
- Estimated compressed size
- Savings percentage
- Compression ratio
- Estimated row count

#### Visualization
- **Strategy Distribution:** Pie chart
- **Savings Distribution:** Histogram
- **Top Tables:** Bar chart
- **Detailed Table:** Sortable DataTable

#### Export Options
- **CSV Export:** Comma-separated values
- **Excel Export:** XLSX format with formatting
- **Timestamp Naming:** Auto-generated filenames
- **Full Data:** All columns exported

### 5. Compression Execution

#### Single Table Execution
- **Table Selection:** Dropdown with details
- **Parameter Configuration:** Dry-run, parallel degree
- **Execution Preview:** Before/after comparison
- **Confirmation Required:** Safety check

**Parameters:**
- Dry Run mode (preview only)
- Parallel degree (1-16)
- Execution confirmation

**Safety Features:**
- Dry run by default
- Confirmation checkbox for production
- Preview of changes
- Rollback capability

#### Batch Execution
- **Multi-Select:** Choose multiple tables
- **Batch Summary:** Total size, savings
- **Parallel Processing:** Efficient execution
- **Progress Tracking:** Monitor all tasks

**Features:**
- Select multiple recommendations
- View aggregate statistics
- Execute in parallel
- Monitor batch progress

#### Execution Monitoring
- **Active Executions:** Real-time progress
- **Progress Bars:** Visual indicators
- **Status Updates:** Automatic refresh
- **Recent History:** Completed executions

**Monitoring Features:**
- Live progress percentage
- Execution status (PENDING, RUNNING, COMPLETED, FAILED)
- Elapsed time
- Manual refresh option

### 6. Execution History

#### Historical Data
- **Date Range Filtering:** Custom periods
- **Status Filtering:** Success/failure
- **Detailed Metrics:** Per-execution stats
- **Export Capability:** CSV/Excel

**Timeline Features:**
- Executions over time (line chart)
- Status distribution (pie chart)
- Strategy breakdown (bar chart)
- Savings distribution (histogram)

#### Analytics
- **Success Rate:** Overall and per-strategy
- **Average Savings:** Trends over time
- **Top Performers:** Best compression results
- **Strategy Comparison:** Performance metrics

**Metrics:**
- Total executions
- Success rate percentage
- Average savings
- Unique tables processed

#### Visual Analytics
- **Timeline Chart:** Daily execution counts
- **Status Pie Chart:** Success vs failure
- **Strategy Bar Chart:** Executions per strategy
- **Savings Histogram:** Distribution analysis
- **Top Tables Chart:** Best savings

### 7. Strategy Management

#### Strategy Overview
- **All Strategies:** Complete list
- **Detailed Info:** Descriptions and use cases
- **Performance Metrics:** Actual results
- **Best Practices:** Recommendations

**Strategies:**
1. **QUERY LOW**
   - Moderate compression (3-5x)
   - Minimal query impact
   - Active transactional tables

2. **QUERY HIGH**
   - High compression (5-8x)
   - Slight query overhead
   - Data warehouse facts

3. **ARCHIVE LOW**
   - High compression (5-10x)
   - Some query overhead
   - Archive/reporting tables

4. **ARCHIVE HIGH**
   - Maximum compression (10-15x)
   - Higher query overhead
   - Long-term archival

#### Strategy Comparison
- **Performance Comparison:** Side-by-side metrics
- **Table-Specific Analysis:** Per-table recommendations
- **Visual Comparison:** Charts and graphs
- **Best Strategy Selection:** AI-powered recommendations

**Comparison Features:**
- Compare all strategies for specific table
- View estimated sizes
- Calculate savings for each
- Recommend best option

#### Selection Guide
- **Use Case Matching:** Scenario-based recommendations
- **Performance Impact:** Query overhead analysis
- **Compression Ratios:** Expected results
- **Best Practices:** Industry standards

### 8. Data Visualization

#### Chart Types
- **Bar Charts:** Strategy comparison, top tables
- **Pie Charts:** Distribution analysis
- **Line Charts:** Timeline trends
- **Histograms:** Savings distribution
- **Combo Charts:** Multi-metric display

**Powered by Plotly:**
- Interactive charts
- Zoom and pan
- Hover tooltips
- Export to PNG
- Responsive design

#### Visual Features
- **Color Coding:** Status indicators
- **Hover Details:** Additional information
- **Interactive Legends:** Toggle visibility
- **Export Options:** PNG, SVG, PDF
- **Responsive Layout:** Mobile-friendly

### 9. Export & Reporting

#### Export Formats
- **CSV:** Plain text, universal compatibility
- **Excel:** Formatted with formulas
- **JSON:** API integration
- **PDF:** Future enhancement

**Export Features:**
- Timestamped filenames
- Full data inclusion
- Formatted columns
- Multiple sheets (Excel)

#### Report Generation
- **Summary Reports:** Key metrics
- **Detailed Reports:** Full data
- **Custom Reports:** User-defined
- **Scheduled Reports:** Future enhancement

### 10. System Integration

#### Database Integration
- **Connection Pooling:** Efficient resource use
- **Query Optimization:** Indexed queries
- **Error Handling:** Graceful degradation
- **Transaction Management:** ACID compliance

**oracledb Features:**
- Connection pool (2-10 connections)
- Automatic reconnection
- Query timeout handling
- Parameter binding

#### ORDS API Integration
- **RESTful Endpoints:** Modern API
- **JSON Responses:** Standard format
- **Error Handling:** Consistent errors
- **Authentication:** Basic Auth

**API Features:**
- SSL/TLS support
- Request timeout
- Retry logic
- Error messages

#### Real-Time Updates
- **Auto Refresh:** Configurable intervals
- **Live Monitoring:** Active executions
- **Status Polling:** Background checks
- **Cache Management:** Performance optimization

### 11. User Interface

#### Navigation
- **Sidebar Menu:** Icon-based navigation
- **Breadcrumbs:** Current location
- **Quick Actions:** One-click features
- **Search:** Filter and find

**Menu Structure:**
- Dashboard (overview)
- Analysis (compression analysis)
- Recommendations (candidates)
- Execution (compress tables)
- History (past executions)
- Strategies (strategy info)

#### Responsive Design
- **Mobile Support:** Touch-friendly
- **Tablet Optimized:** Medium screens
- **Desktop Enhanced:** Full features
- **Accessibility:** WCAG compliant

#### User Experience
- **Loading Indicators:** Spinners and progress bars
- **Error Messages:** Clear and actionable
- **Success Notifications:** Confirmation messages
- **Help Text:** Contextual tooltips

### 12. Administration

#### Configuration Management
- **Environment Variables:** `.env` file
- **Runtime Configuration:** Streamlit config
- **Database Settings:** Connection parameters
- **API Settings:** ORDS configuration

#### Monitoring
- **Connection Status:** Database and API
- **Error Logging:** Application logs
- **Performance Metrics:** Response times
- **Usage Statistics:** User activity

**Monitoring Features:**
- Real-time connection status
- Error rate tracking
- Response time monitoring
- Session management

#### Maintenance
- **Log Rotation:** Automatic cleanup
- **Cache Clearing:** Manual and automatic
- **Session Cleanup:** Timeout handling
- **Database Maintenance:** Connection pool

### 13. Performance Optimization

#### Caching
- **Query Results:** Streamlit cache
- **API Responses:** Client-side cache
- **Static Data:** Long-term cache
- **User Sessions:** Session state

**Cache Strategies:**
- @st.cache_resource for connections
- @st.cache_data for queries
- TTL-based expiration
- Manual cache clearing

#### Query Optimization
- **Indexed Queries:** Efficient lookups
- **Parameterized Queries:** SQL injection prevention
- **Batch Operations:** Reduced round-trips
- **Connection Pooling:** Resource efficiency

#### UI Performance
- **Lazy Loading:** Load on demand
- **Pagination:** Limit results
- **Incremental Updates:** Partial refreshes
- **Compression:** Minimize data transfer

### 14. Security Features

#### Authentication
- Password protection
- Session management
- Login attempt limiting
- Automatic logout

#### Data Security
- SSL/TLS encryption
- SQL injection prevention
- XSS protection
- CSRF tokens

#### Access Control
- Role-based access (future)
- Audit logging
- Session tracking
- IP restrictions (future)

### 15. Extensibility

#### Custom Pages
- Easy page addition
- Template structure
- Consistent styling
- Menu integration

#### API Extensions
- New endpoints
- Custom queries
- Data transformations
- Integration hooks

#### Theme Customization
- Color schemes
- Fonts and typography
- Layout options
- Component styling

## 🔧 Configuration Options

### Application Settings

| Setting | Description | Default |
|---------|-------------|---------|
| `APP_TITLE` | Dashboard title | HCC Compression Advisor |
| `APP_ICON` | Dashboard icon | 📊 |
| `SESSION_TIMEOUT_MINUTES` | Session timeout | 30 |
| `MAX_LOGIN_ATTEMPTS` | Login attempt limit | 3 |

### Database Settings

| Setting | Description | Default |
|---------|-------------|---------|
| `DB_HOST` | Database host | localhost |
| `DB_PORT` | Database port | 1521 |
| `DB_SERVICE` | Service name | XEPDB1 |
| `POOL_MIN` | Min connections | 2 |
| `POOL_MAX` | Max connections | 10 |

### API Settings

| Setting | Description | Default |
|---------|-------------|---------|
| `ORDS_BASE_URL` | ORDS base URL | - |
| `API_TIMEOUT` | Request timeout | 30s |

### Chart Settings

| Setting | Description | Default |
|---------|-------------|---------|
| `CHART_COLORS` | Color scheme | Blues |
| Chart library | Plotly | - |

## 📚 Use Cases

### Development Environment
- Test compression strategies
- Prototype changes
- Debug issues
- Training users

### Production Environment
- Manage compression
- Monitor executions
- Analyze results
- Generate reports

### Analysis & Planning
- Identify candidates
- Compare strategies
- Estimate savings
- Plan migrations

### Reporting & Compliance
- Track savings
- Audit executions
- Document decisions
- Export data

## 🎓 Best Practices

1. **Always use dry-run first**
2. **Backup before compression**
3. **Monitor during execution**
4. **Review history regularly**
5. **Export data for records**
6. **Update credentials regularly**
7. **Enable SSL in production**
8. **Set strong passwords**

---

For detailed usage instructions, see [QUICKSTART.md](QUICKSTART.md)
For complete documentation, see [README.md](README.md)
