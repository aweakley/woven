#!/usr/bin/env python
"""
Anything related to deploying your project modules, media, and data
"""
import os, shutil, sys

from django.core.servers.basehttp import AdminMediaHandler
from django.template.loader import render_to_string

from fabric.state import env
from fabric.operations import local, run, put, sudo
from fabric.decorators import runs_once
from fabric.contrib.files import exists
from fabric.contrib.console import confirm
#Required for a bug in 0.9
from fabric.version import get_version

from woven.deployment import deploy_files, run_once_per_host_version
from woven.environment import deployment_root, _root_domain

@runs_once
def _make_local_sitesettings(overwrite=False):
    local_settings_dir = os.path.join(os.getcwd(),env.project_name,'sitesettings')
    if not os.path.exists(local_settings_dir) or overwrite:
        if overwrite:
            shutil.rmtree(local_settings_dir,ignore_errors=True)
        os.mkdir(local_settings_dir)
        f = open(os.path.join(local_settings_dir,'__init__.py'),"w")
        f.close()

    settings_file_path = os.path.join(local_settings_dir,'settings.py')
    if not os.path.exists(settings_file_path):
        root_domain = _root_domain()    
        u_domain = root_domain.replace('.','_')
        output = render_to_string('woven/sitesettings.txt',
                {"deployment_root":deployment_root(),
                "site_id":"1",
                "project_name": env.project_name,
                "project_fullname": env.project_fullname,
                "u_domain":u_domain,
                "domain":root_domain,
                "user":env.user},
            )
                    
        f = open(settings_file_path,"w+")
        f.writelines(output)
        f.close()
        
        #create a convenience settings file link for the first site
        settings_file_path = os.path.join(local_settings_dir,''.join([u_domain,'.py']))
        if not os.path.exists(settings_file_path):
            f = open(settings_file_path, "w+")
            f.write("from %s.sitesettings.settings import *"% env.project_name)
            f.write("\nSITE_ID=1\n")
            f.close()
            #copy manage.py into that directory
            manage_path = os.path.join(os.getcwd(),env.project_name,'manage.py')
            dest_manage_path = os.path.join(os.getcwd(),env.project_name,'sitesettings','manage.py')
            shutil.copy(manage_path, dest_manage_path)
    return

@run_once_per_host_version
def deploy_project():
    """
    Deploy to the project directory in the virtualenv
    """
    
    project_root = '/'.join([deployment_root(),'env',env.project_fullname,'project'])
    local_dir = os.getcwd()
    
    if env.verbosity:
        print env.host,"DEPLOYING project", env.project_fullname
    #Exclude a few things that we don't want deployed as part of the project folder
    rsync_exclude = ['*.pyc','*.log','.*','/build','/dist','/media*','/static*','/www','/public','/templates']

    #make site local settings if they don't already exist
    _make_local_sitesettings()
    created = deploy_files(local_dir, project_root, rsync_exclude=rsync_exclude)
    if not env.patch:
        #hook the project into sys.path - #TODO make the python version not fixed
        link_name = '/'.join([deployment_root(),'env',env.project_fullname,'lib/python2.6/site-packages',env.project_name])
        target = '/'.join([project_root,env.project_name])
        run(' '.join(['ln -s',target,link_name]))
    
    return created

def deploy_sitesettings():
    """
    Deploy to the project directory in the virtualenv
    """
    
    sitesettings = '/'.join([deployment_root(),'env',env.project_fullname,'project',env.project_name,'sitesettings'])
    local_dir = os.path.join(os.getcwd(),env.project_name,'sitesettings')
 
    created = deploy_files(local_dir, sitesettings)
    if env.verbosity and created:
        print env.host,"DEPLOYING sitesettings"
        for path in created:
            tail = path.split('/')[-1]
            print ' * uploaded',tail

@run_once_per_host_version
def deploy_templates():
    """
    Deploy any templates from your shortest TEMPLATE_DIRS setting
    """
    
    deployed = None
    if not hasattr(env, 'project_template_dir'):
        #the normal pattern would mean the shortest path is the main one.
        #its probably the last listed
        length = 1000   
        for dir in env.TEMPLATE_DIRS:
            if dir:
                len_dir = len(dir)
                if len_dir < length:
                    length = len_dir
                    env.project_template_dir = dir
    
    if hasattr(env,'project_template_dir'):
        remote_dir = '/'.join([deployment_root(),'env',env.project_fullname,'templates'])
        if env.verbosity:
            print env.host,"DEPLOYING templates", remote_dir
        deployed = deploy_files(env.project_template_dir,remote_dir)
    return deployed
     
@run_once_per_host_version
def deploy_static():
    """
    Deploy static (application) versioned media
    """
    if (not env.STATIC_ROOT and not env.ADMIN_MEDIA_PREFIX) or 'http://' in env.STATIC_URL: return
        
    remote_dir = '/'.join([deployment_root(),'env',env.project_fullname,'static'])
    
    #if app media is not handled by django-staticfiles we can install admin media by default
    if 'django.contrib.admin' in env.INSTALLED_APPS and not env.STATIC_ROOT:
        if env.MEDIA_URL in env.ADMIN_MEDIA_PREFIX:
            print "ERROR: Your ADMIN_MEDIA_PREFIX must not be on the same path as your MEDIA_URL"
            print "for example you cannot use MEDIA_URL = /media/ and ADMIN_MEDIA_PREFIX = /media/admin/"
            sys.exit(1)
        env.STATIC_URL = env.ADMIN_MEDIA_PREFIX    
        admin = AdminMediaHandler('DummyApp')
        local_dir = admin.media_dir
        remote_dir =  ''.join([remote_dir,env.ADMIN_MEDIA_PREFIX])
    else:
        if env.MEDIA_URL in env.STATIC_URL:
            print "ERROR: Your STATIC_URL must not be on the same path as your MEDIA_URL"
            print "for example you cannot use MEDIA_URL = /media/ and STATIC_URL = /media/static/"
            sys.exit(1)
        elif env.STATIC_ROOT:
            local_dir = env.STATIC_ROOT
            static_url = env.STATIC_URL[1:]
            if static_url:
                remote_dir = '/'.join([remote_dir,static_url])
        else: return
    if env.verbosity:
        print env.host,"DEPLOYING static",remote_dir
    return deploy_files(local_dir,remote_dir)

@run_once_per_host_version       
def deploy_public():
    """
    Deploy MEDIA_ROOT unversioned on host
    """
    if not env.MEDIA_ROOT or 'http://' in env.MEDIA_URL: return
    local_dir = env.MEDIA_ROOT
    
    remote_dir = '/'.join([deployment_root(),'public']) 
    media_url = env.MEDIA_URL[1:]
    if media_url:
        remote_dir = '/'.join([remote_dir,media_url])
    if env.verbosity:
        print env.host,"DEPLOYING public",remote_dir    
    deployed = deploy_files(local_dir,remote_dir)
    
    #make writable for www-data for file uploads
    sudo("chown -R www-data:sudo %s" % remote_dir)
    sudo("chmod -R ug+w %s"% remote_dir)
    return deployed

@runs_once
def deploy_db(rollback=False):
    """
    Deploy a sqlite database from development
    """
    db_name = ''.join([env.project_name,'.db'])
    db_dir = '/'.join([deployment_root(),'database'])
    db_path = '/'.join([db_dir,db_name])
    if not rollback:
        if env.DEFAULT_DATABASE_ENGINE=='django.db.backends.sqlite3' and not exists(db_path):
            if env.verbosity:
                print env.host,"DEPLOYING DEFAULT SQLITE DATABASE",db_path
            if not os.path.exists(env.DEFAULT_DATABASE_NAME) or not env.DEFAULT_DATABASE_NAME:
                print "ERROR: the database does not exist. Run python manage.py syncdb to create your database first."
                sys.exit(1)
            run('mkdir -p '+db_dir)
            put(env.DEFAULT_DATABASE_NAME,db_path)
            #directory and file must be writable by webserver
            sudo("chown -R %s:www-data %s"% (env.user,db_dir))
            sudo("chmod -R ug+w %s"% db_dir)
    elif rollback and env.DEFAULT_DATABASE_ENGINE=='django.db.backends.sqlite3':
        if env.INTERACTIVE:
            delete = confirm('DELETE the database on the host?',default=False)
            if delete:
                run('rm -f '+db_name)
    return
