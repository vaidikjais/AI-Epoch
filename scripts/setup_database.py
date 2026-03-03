"""
Database setup utility for PostgreSQL.
This script helps set up and manage the PostgreSQL database.
"""
import os
import sys
import subprocess
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.core.config import settings
from app.core.database import sync_engine, create_db_and_tables


def check_postgres_connection():
    """Check if PostgreSQL connection is working."""
    try:
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            print("✅ PostgreSQL connection successful!")
            return True
    except Exception as e:
        print(f"❌ PostgreSQL connection failed: {e}")
        return False


def create_database_if_not_exists():
    """Create the database if it doesn't exist."""
    # Always use PostgreSQL now
    
    try:
        # Extract database name from URL
        db_name = settings.POSTGRES_DB
        
        # Create connection to PostgreSQL server (without specific database)
        server_url = f"postgresql://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/postgres"
        
        from sqlalchemy import create_engine, text
        server_engine = create_engine(server_url)
        
        with server_engine.connect() as conn:
            # Check if database exists
            result = conn.execute(text(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'"))
            if result.fetchone():
                print(f"✅ Database '{db_name}' already exists")
            else:
                # Create database
                conn.execute(text("COMMIT"))  # End any existing transaction
                conn.execute(text(f"CREATE DATABASE {db_name}"))
                print(f"✅ Created database '{db_name}'")
        
        return True
    except Exception as e:
        print(f"❌ Failed to create database: {e}")
        return False


def setup_database():
    """Set up the database and create tables."""
    print("🔧 Setting up database...")
    print(f"Database URL: {settings.DATABASE_URL}")
    
    print("📊 Using PostgreSQL")
    if not create_database_if_not_exists():
        return False
    
    if not check_postgres_connection():
        return False
    
    try:
        create_db_and_tables()
        print("✅ Database tables created successfully!")
        return True
    except Exception as e:
        print(f"❌ Failed to create tables: {e}")
        return False


def install_postgres_macos():
    """Helper to install PostgreSQL on macOS."""
    print("📦 Installing PostgreSQL on macOS...")
    try:
        subprocess.run(["brew", "install", "postgresql@15"], check=True)
        subprocess.run(["brew", "services", "start", "postgresql@15"], check=True)
        print("✅ PostgreSQL installed and started!")
        print("🔑 Create a database user with:")
        print("   createuser -s postgres")
        print("   createdb newsletter")
    except subprocess.CalledProcessError:
        print("❌ Failed to install PostgreSQL. Please install manually.")
    except FileNotFoundError:
        print("❌ Homebrew not found. Please install Homebrew first or install PostgreSQL manually.")


def main():
    """Main setup function."""
    print("🚀 Newsletter Database Setup")
    print("=" * 30)
    
    # Check if .env file exists
    env_file = Path(__file__).parent.parent / ".env"
    if not env_file.exists():
        print("⚠️  No .env file found. Please copy .env.example to .env and configure your database settings.")
        return
    
    print(f"Current database URL: {settings.DATABASE_URL}")
    
    print("\n🐘 PostgreSQL Setup")
    print("Make sure PostgreSQL is running and accessible.")
    print("On macOS, you can install it with: brew install postgresql@15")
    
    choice = input("\nDo you want to install PostgreSQL with Homebrew? (y/N): ").lower()
    if choice == 'y':
        install_postgres_macos()
    
    print("\n🔧 Setting up database...")
    if setup_database():
        print("\n🎉 Database setup complete!")
        print("You can now start the application with:")
        print("   uvicorn app.main:app --reload")
    else:
        print("\n❌ Database setup failed. Please check your configuration.")


if __name__ == "__main__":
    main()