#!/usr/bin/env python3
"""
HIPAA-compliant file cleanup system for uploaded patient data
"""
import boto3
import json
import os
import time
from datetime import datetime, timedelta
from typing import List, Dict
import threading
import atexit

from s3_config import get_upload_bucket

class HIPAAFileManager:
    """
    HIPAA-compliant file manager that ensures uploaded files are deleted within 2 hours
    """
    
    def __init__(self):
        self.bucket_name = get_upload_bucket()
        self.s3_client = boto3.client('s3')
        self.cleanup_registry_key = "hipaa-cleanup/file_registry.json"
        #self.max_retention_hours = 2
        self.max_retention_minutes = 2
        
        # Register cleanup on exit
        atexit.register(self.emergency_cleanup)
    
    def register_file_for_cleanup(self, s3_uri: str, upload_time: datetime = None) -> bool:
        """
        Register a file for HIPAA-compliant cleanup
        """
        if upload_time is None:
            upload_time = datetime.now()
        
        try:
            # Extract file key from S3 URI
            file_key = s3_uri.replace(f"s3://{self.bucket_name}/", "")
            
            # Get current registry
            registry = self._get_cleanup_registry()
            
            # Add file to registry
            file_record = {
                "s3_uri": s3_uri,
                "file_key": file_key,
                "upload_time": upload_time.isoformat(),
               # "deletion_time": (upload_time + timedelta(hours=self.max_retention_hours)).isoformat(),
                "deletion_time": (upload_time + timedelta(minutes=self.max_retention_minutes)).isoformat(),
                "status": "pending"
            }
            
            registry[file_key] = file_record
            
            # Save updated registry
            self._save_cleanup_registry(registry)
            
            print(f"📋 Registered for HIPAA cleanup: {s3_uri}")
            print(f"⏰ Scheduled deletion: {file_record['deletion_time']}")
            
            # Start immediate cleanup thread for this file
            #self._schedule_file_deletion(file_key, self.max_retention_hours * 3600)
            self._schedule_file_deletion(file_key, self.max_retention_minutes * 60)
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to register file for cleanup: {e}")
            return False
    
    def _get_cleanup_registry(self) -> Dict:
        """
        Get the current cleanup registry from S3
        """
        try:
            response = self.s3_client.get_object(
                Bucket=self.bucket_name,
                Key=self.cleanup_registry_key
            )
            content = response['Body'].read().decode('utf-8')
            return json.loads(content)
        except self.s3_client.exceptions.NoSuchKey:
            # Registry doesn't exist yet
            return {}
        except Exception as e:
            print(f"⚠️ Error reading cleanup registry: {e}")
            return {}
    
    def _save_cleanup_registry(self, registry: Dict) -> bool:
        """
        Save the cleanup registry to S3
        """
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=self.cleanup_registry_key,
                Body=json.dumps(registry, indent=2),
                ContentType='application/json'
            )
            return True
        except Exception as e:
            print(f"❌ Error saving cleanup registry: {e}")
            return False
    
    def _schedule_file_deletion(self, file_key: str, delay_seconds: int):
        """
        Schedule a file for deletion after a delay
        """
        def delayed_delete():
            time.sleep(delay_seconds)
            self._delete_file_now(file_key)
        
        # Start deletion thread
        thread = threading.Thread(target=delayed_delete, daemon=True)
        thread.start()
    
    def _delete_file_now(self, file_key: str) -> bool:
        """
        Delete a file immediately and update registry
        """
        try:
            # Delete the actual file
            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=file_key
            )
            
            # Update registry
            registry = self._get_cleanup_registry()
            if file_key in registry:
                registry[file_key]['status'] = 'deleted'
                registry[file_key]['actual_deletion_time'] = datetime.now().isoformat()
                self._save_cleanup_registry(registry)
            
            print(f"🧹 HIPAA cleanup completed: s3://{self.bucket_name}/{file_key}")
            return True
            
        except Exception as e:
            print(f"❌ Failed to delete file {file_key}: {e}")
            
            # Update registry with error
            registry = self._get_cleanup_registry()
            if file_key in registry:
                registry[file_key]['status'] = 'error'
                registry[file_key]['error'] = str(e)
                registry[file_key]['error_time'] = datetime.now().isoformat()
                self._save_cleanup_registry(registry)
            
            return False
    
    def cleanup_overdue_files(self) -> int:
        """
        Clean up any files that are overdue for deletion (HIPAA compliance check)
        """
        print("🔍 Checking for overdue HIPAA files...")
        
        try:
            registry = self._get_cleanup_registry()
            current_time = datetime.now()
            deleted_count = 0
            
            for file_key, record in registry.items():
                if record['status'] == 'pending':
                    deletion_time = datetime.fromisoformat(record['deletion_time'])
                    
                    if current_time > deletion_time:
                        print(f"⚠️ OVERDUE FILE DETECTED: {file_key}")
                        print(f"   Should have been deleted: {deletion_time}")
                        print(f"   Current time: {current_time}")
                        
                        # Delete immediately
                        if self._delete_file_now(file_key):
                            deleted_count += 1
            
            if deleted_count > 0:
                print(f"🚨 HIPAA COMPLIANCE: Deleted {deleted_count} overdue files")
            else:
                print(f"✅ HIPAA COMPLIANCE: No overdue files found")
            
            return deleted_count
            
        except Exception as e:
            print(f"❌ Error during overdue file cleanup: {e}")
            return 0
    
    def emergency_cleanup(self):
        """
        Emergency cleanup on application exit (HIPAA safety net)
        """
        print("🚨 Emergency HIPAA cleanup on exit...")
        
        try:
            # Clean up any overdue files
            self.cleanup_overdue_files()
            
            # Also clean up files from the current session that might not be registered
            current_time = datetime.now()
           # cutoff_time = current_time - timedelta(hours=self.max_retention_hours)
            cutoff_time = current_time - timedelta(minutes=self.max_retention_minutes)
            
            # List all files in uploads/ prefix
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix='uploads/'
            )
            
            emergency_deleted = 0
            for obj in response.get('Contents', []):
                if obj['LastModified'].replace(tzinfo=None) < cutoff_time:
                    try:
                        self.s3_client.delete_object(
                            Bucket=self.bucket_name,
                            Key=obj['Key']
                        )
                        emergency_deleted += 1
                        print(f"🚨 Emergency deleted: {obj['Key']}")
                    except Exception as e:
                        print(f"⚠️ Could not emergency delete {obj['Key']}: {e}")
            
            if emergency_deleted > 0:
                print(f"🚨 Emergency cleanup: Deleted {emergency_deleted} old files")
            
        except Exception as e:
            print(f"❌ Emergency cleanup failed: {e}")
    
    def get_cleanup_status(self) -> Dict:
        """
        Get the current status of all files in the cleanup system
        """
        registry = self._get_cleanup_registry()
        
        status = {
            "total_files": len(registry),
            "pending_deletion": 0,
            "deleted": 0,
            "errors": 0,
            "overdue": 0
        }
        
        current_time = datetime.now()
        
        for record in registry.values():
            if record['status'] == 'pending':
                status['pending_deletion'] += 1
                deletion_time = datetime.fromisoformat(record['deletion_time'])
                if current_time > deletion_time:
                    status['overdue'] += 1
            elif record['status'] == 'deleted':
                status['deleted'] += 1
            elif record['status'] == 'error':
                status['errors'] += 1
        
        return status

# Global instance
hipaa_manager = HIPAAFileManager()

def register_hipaa_file(s3_uri: str) -> bool:
    """
    Register a file for HIPAA-compliant cleanup (2-hour deletion)
    """
    return hipaa_manager.register_file_for_cleanup(s3_uri)

def check_hipaa_compliance() -> Dict:
    """
    Check HIPAA compliance status
    """
    return hipaa_manager.get_cleanup_status()

def force_hipaa_cleanup() -> int:
    """
    Force cleanup of overdue files (for manual compliance check)
    """
    return hipaa_manager.cleanup_overdue_files()