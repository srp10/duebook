"""Emit a CloudFormation template with the standalone worker embedded; no packaging deps."""
import json
from pathlib import Path

code = (Path(__file__).resolve().parents[1] / 'src/duebook/cloud_worker.py').read_text()
ref = lambda name: {'Ref': name}
att = lambda name, key: {'Fn::GetAtt': [name, key]}
sub = lambda value: {'Fn::Sub': value}
template = {
 'AWSTemplateFormatVersion': '2010-09-09',
 'Description': 'Private Duebook email worker. Only explicitly approved reminders are sent.',
 'Parameters': {'Email': {'Type': 'String', 'NoEcho': True}},
 'Resources': {
  'State': {'Type': 'AWS::S3::Bucket', 'DeletionPolicy': 'Retain',
   'UpdateReplacePolicy': 'Retain', 'Properties': {
    'PublicAccessBlockConfiguration': {k: True for k in [
      'BlockPublicAcls','BlockPublicPolicy','IgnorePublicAcls','RestrictPublicBuckets']},
    'BucketEncryption': {'ServerSideEncryptionConfiguration': [
      {'ServerSideEncryptionByDefault': {'SSEAlgorithm':'AES256'}}]}}},
  'Logs': {'Type': 'AWS::Logs::LogGroup', 'Properties': {
    'LogGroupName': sub('/aws/lambda/${AWS::StackName}-worker'), 'RetentionInDays': 14}},
  'WorkerRole': {'Type': 'AWS::IAM::Role', 'Properties': {
    'AssumeRolePolicyDocument': {'Version':'2012-10-17','Statement': [{
     'Effect':'Allow','Principal':{'Service':'lambda.amazonaws.com'},'Action':'sts:AssumeRole'}]},
    'Policies':[{'PolicyName':'OnlyDuebookStateAndVerifiedEmail', 'PolicyDocument': {
     'Version':'2012-10-17','Statement': [
      {'Effect':'Allow','Action':['s3:ListBucket'],'Resource':att('State','Arn'),
       'Condition':{'StringEquals':{'s3:prefix':'reminders.json'}}},
      {'Effect':'Allow','Action':['s3:GetObject','s3:PutObject'],
       'Resource':sub('${State.Arn}/reminders.json')},
      {'Effect':'Allow','Action':['ses:SendEmail'],
       'Resource':sub('arn:${AWS::Partition}:ses:${AWS::Region}:${AWS::AccountId}:identity/${Email}'),
       'Condition':{'ForAllValues:StringEquals':{'ses:Recipients':[ref('Email')]},
                    'StringEquals':{'ses:FromAddress':ref('Email')}}},
      {'Effect':'Allow','Action':['logs:CreateLogStream','logs:PutLogEvents'],
       'Resource':att('Logs','Arn')}
     ]}}]}},
  'Worker': {'Type':'AWS::Lambda::Function','Properties': {
    'FunctionName':sub('${AWS::StackName}-worker'), 'Runtime':'python3.12',
    'Handler':'index.handler','Role':att('WorkerRole','Arn'), 'Timeout':120,
    'MemorySize':128,'ReservedConcurrentExecutions':1,
    'Environment':{'Variables':{'STATE_BUCKET':ref('State'),
      'EMAIL_FROM':ref('Email'),'EMAIL_TO':ref('Email')}},'Code':{'ZipFile':code}}},
  'ScheduleRole': {'Type':'AWS::IAM::Role','Properties':{
    'AssumeRolePolicyDocument':{'Version':'2012-10-17','Statement':[{
      'Effect':'Allow','Principal':{'Service':'scheduler.amazonaws.com'},
      'Action':'sts:AssumeRole','Condition':{'StringEquals':{'aws:SourceAccount':ref('AWS::AccountId')}}}]},
    'Policies':[{'PolicyName':'InvokeOnlyDuebook','PolicyDocument':{
      'Version':'2012-10-17','Statement':[{'Effect':'Allow','Action':'lambda:InvokeFunction',
      'Resource':att('Worker','Arn')}]}}]}},
  'Tick':{'Type':'AWS::Scheduler::Schedule','Properties':{
    'ScheduleExpression':'rate(1 minute)','FlexibleTimeWindow':{'Mode':'OFF'},
    'Target':{'Arn':att('Worker','Arn'),'RoleArn':att('ScheduleRole','Arn'),
     'Input':'{"action":"tick"}','RetryPolicy':{'MaximumRetryAttempts':2,'MaximumEventAgeInSeconds':300}}}}
 },
 'Outputs': {'Function':{'Value':att('Worker','Arn')},'StateBucket':{'Value':ref('State')}}
}
print(json.dumps(template, indent=2))
