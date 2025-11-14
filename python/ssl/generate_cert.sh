#!/bin/bash
#
# SSL Certificate Generator for HCC Compression Advisor
# Generates self-signed SSL certificates for HTTPS support
#

set -e

# Configuration
DAYS=365
COUNTRY="US"
STATE="California"
CITY="San Francisco"
ORG="HCC Compression Advisor"
OU="IT Department"
CN="localhost"
EMAIL="admin@example.com"

# Output files
CERT_FILE="cert.pem"
KEY_FILE="key.pem"

echo "Generating self-signed SSL certificate..."
echo "================================================"
echo "Common Name: $CN"
echo "Organization: $ORG"
echo "Valid for: $DAYS days"
echo "================================================"
echo ""

# Generate private key and certificate
openssl req -x509 -newkey rsa:4096 \
    -keyout "$KEY_FILE" \
    -out "$CERT_FILE" \
    -days "$DAYS" \
    -nodes \
    -subj "/C=$COUNTRY/ST=$STATE/L=$CITY/O=$ORG/OU=$OU/CN=$CN/emailAddress=$EMAIL" \
    -addext "subjectAltName=DNS:localhost,DNS:*.localhost,IP:127.0.0.1"

echo ""
echo "✅ SSL certificate generated successfully!"
echo ""
echo "Files created:"
echo "  - Certificate: $CERT_FILE"
echo "  - Private Key: $KEY_FILE"
echo ""
echo "To use with Streamlit:"
echo "  streamlit run app.py --server.sslCertFile=$CERT_FILE --server.sslKeyFile=$KEY_FILE"
echo ""
echo "⚠️  Note: This is a self-signed certificate for development only."
echo "    For production, use a certificate from a trusted CA."
echo ""

# Set secure permissions
chmod 600 "$KEY_FILE"
chmod 644 "$CERT_FILE"

echo "Permissions set:"
echo "  - $KEY_FILE: 600 (owner read/write only)"
echo "  - $CERT_FILE: 644 (owner read/write, others read)"
echo ""
