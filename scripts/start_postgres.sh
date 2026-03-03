#!/bin/bash
# Quick PostgreSQL setup using Docker

echo "🐘 Starting PostgreSQL with Docker..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

# Start PostgreSQL container
docker run --name newsletter-postgres \
    -e POSTGRES_DB=newsletter \
    -e POSTGRES_USER=postgres \
    -e POSTGRES_PASSWORD=postgres \
    -p 5432:5432 \
    -d postgres:15

echo "✅ PostgreSQL is starting..."
echo "📝 Connection details:"
echo "   Host: localhost"
echo "   Port: 5432"
echo "   Database: newsletter"
echo "   Username: postgres"
echo "   Password: postgres"
echo ""
echo "🔗 Connection URL: postgresql://postgres:postgres@localhost:5432/newsletter"
echo ""
echo "To stop: docker stop newsletter-postgres"
echo "To remove: docker rm newsletter-postgres"