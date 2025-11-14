# Oracle 23c Free Database with HCC Compression Advisor
# Base image: Oracle Database 23c Free Edition
FROM container-registry.oracle.com/database/free:latest

# Metadata
LABEL maintainer="HCC Compression Advisor Team"
LABEL description="Oracle 23c Free with HCC Compression Advisor pre-configured"
LABEL version="1.0.0"

# Environment variables
ENV ORACLE_BASE=/opt/oracle \
    ORACLE_HOME=/opt/oracle/product/23c/dbhomeFree \
    ORACLE_SID=FREE \
    PATH=$ORACLE_HOME/bin:$PATH \
    COMPRESSION_USER=COMPRESSION_MGR \
    COMPRESSION_TS=SCRATCH_TS \
    INSTALL_DIR=/opt/oracle/scripts/setup

# Switch to root for directory creation
USER root

# Note: Oracle Database Free container has minimal tools pre-installed
# Additional packages can be installed if needed using:
# RUN dnf install -y <package> && dnf clean all

# Create directories for scripts and logs
RUN mkdir -p ${INSTALL_DIR} \
    && mkdir -p /opt/oracle/oradata/logs \
    && mkdir -p /opt/oracle/compression_advisor \
    && chown -R oracle:oinstall /opt/oracle/compression_advisor \
    && chmod -R 755 /opt/oracle/compression_advisor

# Copy initialization scripts
COPY --chown=oracle:oinstall init-scripts/*.sql ${INSTALL_DIR}/
COPY --chown=oracle:oinstall init-scripts/*.sh ${INSTALL_DIR}/

# Make shell scripts executable
RUN chmod +x ${INSTALL_DIR}/*.sh

# Copy compression advisor installation files
# These will be mounted at runtime via docker-compose
RUN mkdir -p /opt/oracle/compression_advisor/install

# Switch back to oracle user
USER oracle

# Expose Oracle Database and ORDS ports
# 1521: Oracle Database listener
# 5500: Oracle Enterprise Manager Express
# 8080: ORDS (Oracle REST Data Services)
EXPOSE 1521 5500 8080

# Health check to verify database is running
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \
    CMD ${ORACLE_HOME}/bin/sqlplus -s sys/${ORACLE_PWD}@localhost:1521/FREE as sysdba <<< "SELECT 'healthy' FROM dual;" || exit 1

# Default command - runs Oracle Database startup
CMD ["/bin/bash", "-c", "exec $ORACLE_BASE/$RUN_FILE"]
