pipeline {
    agent any

    environment {
        COMPOSE_FILE = 'docker-compose.yaml'
        IMAGE_NAME = 'crypalgos-api' // Used for cleanup
    }

    stages {
        stage('Checkout') {
            steps {
                script {
                    // Use the github_pat credential for authentication
                    checkout([$class: 'GitSCM', 
                        branches: [[name: '*/master']], // Adjust branch as needed, usually 'master' or 'main'
                        doGenerateSubmoduleConfigurations: false, 
                        extensions: [[$class: 'CleanBeforeCheckout']], 
                        submoduleCfg: [], 
                        userRemoteConfigs: [[credentialsId: 'github_pat', url: 'https://github.com/crypalgos/api.git']]
                    ])
                }
            }
        }

        stage('Setup Environment') {
            steps {
                script {
                    // Use the api_prod_env secret file credential
                    withCredentials([file(credentialsId: 'api_prod_env', variable: 'API_PROD_ENV_FILE')]) {
                        // Copy the secret file content to .env.prod which docker-compose uses
                        sh 'cp $API_PROD_ENV_FILE .env.prod'
                    }
                    
                    // Verify the file exists (optional, for debugging)
                    sh 'ls -la .env.prod'
                }
            }
        }

        stage('Build and Deploy') {
            steps {
                script {
                    // Build and start the containers using docker-compose
                    // -d: Detached mode
                    // --build: Build images before starting containers
                    sh 'docker-compose up -d --build'
                }
            }
        }
        
        stage('Cleanup') {
            steps {
                script {
                    // Remove dangling images to save space
                    // This is a good practice when building images locally without pushing
                    sh 'docker image prune -f'
                }
            }
        }
    }

    post {
        always {
            // Clean up the sensitive environment file after deployment
            sh 'rm -f .env.prod'
        }
        success {
            echo 'Deployment successful!'
        }
        failure {
            echo 'Deployment failed!'
        }
    }
}
