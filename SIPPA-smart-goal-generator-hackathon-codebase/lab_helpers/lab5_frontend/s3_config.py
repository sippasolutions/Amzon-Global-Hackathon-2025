"""
S3 Configuration for file uploads
"""
import os
import boto3
from botocore.exceptions import ClientError

# Default S3 bucket name - can be overridden by environment variable
DEFAULT_BUCKET = "sippa-smart-goal-generator-uploads"

def get_upload_bucket():
    """Get the S3 bucket name for file uploads"""
    return os.environ.get('UPLOAD_S3_BUCKET', DEFAULT_BUCKET)

def ensure_bucket_exists(bucket_name=None):
    """
    Ensure the S3 bucket exists, create if it doesn't.
    Returns True if bucket exists/created, False if failed.
    """
    if bucket_name is None:
        bucket_name = get_upload_bucket()
    
    s3_client = boto3.client('s3')
    
    try:
        # Check if bucket exists
        s3_client.head_bucket(Bucket=bucket_name)
        return True
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == '404':
            # Bucket doesn't exist, try to create it
            try:
                # Get current region
                session = boto3.session.Session()
                region = session.region_name or 'us-east-1'
                
                if region == 'us-east-1':
                    # us-east-1 doesn't need LocationConstraint
                    s3_client.create_bucket(Bucket=bucket_name)
                else:
                    s3_client.create_bucket(
                        Bucket=bucket_name,
                        CreateBucketConfiguration={'LocationConstraint': region}
                    )
                
                print(f"✅ Created S3 bucket: {bucket_name}")
                return True
            except ClientError as create_error:
                print(f"❌ Failed to create S3 bucket {bucket_name}: {create_error}")
                return False
        else:
            print(f"❌ Error accessing S3 bucket {bucket_name}: {e}")
            return False

def cleanup_old_uploads(bucket_name=None, minutes_old=2):
    """
    Clean up old uploaded files (optional maintenance function)
    """
    if bucket_name is None:
        bucket_name = get_upload_bucket()
    
    try:
        s3_client = boto3.client('s3')
        from datetime import datetime, timedelta
        
        #cutoff_date = datetime.now() - timedelta(days=days_old)
        #cutoff_date = datetime.now() - timedelta(hours=hours_old)
        cutoff_date = datetime.now() - timedelta(minutes=minutes_old)

        
        # List objects in uploads/ prefix
        response = s3_client.list_objects_v2(
            Bucket=bucket_name,
            Prefix='uploads/'
        )
        
        deleted_count = 0
        for obj in response.get('Contents', []):
            if obj['LastModified'].replace(tzinfo=None) < cutoff_date:
                s3_client.delete_object(Bucket=bucket_name, Key=obj['Key'])
                deleted_count += 1
        
        if deleted_count > 0:
            print(f"🧹 Cleaned up {deleted_count} old files from S3")
        
        return deleted_count
    except Exception as e:
        print(f"⚠️ Error during S3 cleanup: {e}")
        return 0



def schedule_file_cleanup(file_path, delay_minutes=2):
    """
    Schedule a file for cleanup after a delay (for cross-session compatibility)
    """
    if not file_path.startswith('s3://'):
        return
    
    try:
        import threading
        import time
        
        def delayed_cleanup():
            time.sleep(delay_minutes * 60)  # Convert minutes to seconds
            try:
                bucket_name = get_upload_bucket()
                file_key = file_path.replace(f"s3://{bucket_name}/", "")
                s3_client = boto3.client('s3')
                s3_client.delete_object(Bucket=bucket_name, Key=file_key)
                print(f"🧹 Delayed cleanup completed: {file_path}")
            except Exception as e:
                print(f"⚠️ Delayed cleanup failed for {file_path}: {e}")
        
        # Start cleanup thread
        cleanup_thread = threading.Thread(target=delayed_cleanup, daemon=True)
        cleanup_thread.start()
        print(f"⏰ Scheduled cleanup for {file_path} in {delay_minutes} minutes")
        
    except Exception as e:
        print(f"⚠️ Could not schedule cleanup for {file_path}: {e}")